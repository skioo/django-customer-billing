"""
State changes for accounts.

Also, the account is the aggregate root for invoices and charges,
so the creation of those is managed here.

"""
from datetime import date
from typing import Dict, Optional, Sequence, List, Tuple

from django.db import transaction
from django.db.models import Case, Value, When
from moneyed import Money
from structlog import get_logger

from billing.signals import invoice_ready
from ..models import (
    Account,
    Charge,
    Invoice,
    ProductProperty,
    Transaction,
    CARRIED_FORWARD,
    CREDIT_REMAINING,
    total_amount,
)

logger = get_logger()


def close(account_id: str) -> None:
    """
    Closes the account.

    :param account_id: the account to close
    :return: Nothing
    """
    logger.info('closing-account', account_id=account_id)
    with transaction.atomic():
        account = Account.objects.get(pk=account_id)
        account.close()
        account.save()


def reopen(account_id: str) -> None:
    """
    Reopens the account.

    :param account_id: the account to reopen
    :return: Nothing
    """
    logger.info('reopening-account', account_id=account_id)
    with transaction.atomic():
        account = Account.objects.get(pk=account_id)
        account.reopen()
        account.save()


def create_invoices(account_id: str, due_date: date) -> Sequence[Invoice]:
    """
    Creates the invoices for any due positive charges in the account.
    If there are due positive charges in different currencies, one invoice is created for each currency.

    :param account_id: The account to invoice.
    :param due_date: The due date for any invoice that gets created.
    :return: A possibly-empty list of Invoices.
    """
    invoices = []
    with transaction.atomic():
        due_charges = Charge.objects \
            .uninvoiced(account_id=account_id) \
            .charges()
        total = total_amount(due_charges)
        for amount_due in total.monies():
            if amount_due.amount > 0:
                invoice = Invoice.objects.create(account_id=account_id, due_date=due_date)
                Charge.objects \
                    .uninvoiced(account_id=account_id) \
                    .charges() \
                    .in_currency(currency=amount_due.currency) \
                    .update(invoice=invoice)
                invoices.append(invoice)
    logger.info('created-invoices', account_id=str(account_id), invoice_ids=[i.pk for i in invoices])
    for invoice in invoices:
        invoice_ready.send(sender=create_invoices, invoice=invoice)
    return invoices


def add_charge(account_id: str,
               amount: Money,
               reverses_id: Optional[str] = None,
               product_code: Optional[str] = None,
               product_properties: Optional[Dict[str, str]] = None) -> Charge:
    """
    Add a charge to the account.

    :param account_id: The account on which to add the charge
    :param amount:  The amount of the charge
    :param reverses_id: Set this if this charge reverses another one
    :param product_code: A code identifying the type of product cnarged
    :param product_properties: A dict of hames and values.
    :return: The newly created charge.
    """
    logger.info('adding-charge', account_id=account_id, amount=amount, product_code=product_code,
                product_properties=product_properties)

    with transaction.atomic():
        charge = Charge(account_id=account_id,
                        amount=amount)
        if reverses_id:
            charge.reverses_id = reverses_id
        if product_code:
            charge.product_code = product_code
        charge.full_clean(exclude=['id', 'account'])  # Exclude to avoid unnecessary db queries
        charge.save(force_insert=True)

        if product_properties:
            objs = [ProductProperty(charge=charge, name=k, value=v) for k, v in product_properties.items()]
            for o in objs:
                o.full_clean(exclude=['id', 'charge'])  # Exclude to avoid unnecessary db queries
            ProductProperty.objects.bulk_create(objs)

    return charge


def assign_funds_to_account_pending_invoices(account_id: str) -> Sequence[str]:
    """
    Tries to pay pending account invoices (starting from the oldest) with available funds.
    :param account_id: the account on which to perform the operation
    :return: The ids of the invoices that were paid (possibly empty list).
    """
    logger.info('assign-funds-to-pending-invoices', account_id=str(account_id))

    paid_invoice_ids = []
    for invoice in Invoice.objects.filter(status=Invoice.PENDING, account_id=account_id).order_by('due_date'):
        invoice_was_paid = assign_funds_to_invoice(invoice.pk)
        if invoice_was_paid:
            paid_invoice_ids.append(invoice.id)
        else:
            break  # Bail even though there may be funds in another currency to pay more recent invoices.
    logger.info('assign-funds-to-pending-invoices.end', account_id=str(account_id),
                paid_invoice_count=len(paid_invoice_ids))
    return paid_invoice_ids


def assign_funds_to_invoice(invoice_id: str) -> bool:
    """
    Uses the available funds on the account (credits and payments) to pay the given invoice.
    :param invoice_id: The id of the invoice.
    :return: True if the invoice status is paid.

    A lot of side effects may occur in the database:
    - Funds (either payments or credits) may get assigned to the invoice.
    - The invoice status may change.
    - Credits entities may be created.
    """

    logger.info('assign-funds-to-invoice', invoice_id=invoice_id)
    invoice = Invoice.objects.get(pk=invoice_id)
    account_id = invoice.account_id

    #
    # Precondition. Don't touch invoices that are not PENDING
    #
    if invoice.status != Invoice.PENDING:
        logger.info('assign-funds-to-invoice.status-is-not-pending', invoice_id=invoice_id)
        return False

    #
    # Precondition: Only handle invoices in a single currency
    #
    invoice_due_monies = invoice.due().monies()
    if len(invoice_due_monies) != 1:
        logger.info('assign-funds-to-invoice.more-than-one-currency', invoice_id=invoice_id)
        return False
    invoice_due_amount = invoice_due_monies[0].amount
    invoice_due_currency = invoice_due_monies[0].currency

    #
    # 1. Collect funds as long as long as we need them
    #
    if invoice_due_amount > 0:

        payments = Transaction.successful \
            .payments() \
            .uninvoiced(account_id=account_id) \
            .in_currency(invoice_due_currency) \
            .order_by('created')

        credits = Charge.objects \
            .credits() \
            .uninvoiced(account_id=account_id) \
            .in_currency(invoice_due_currency) \
            .order_by('created')

        funds = list(credits) + list(payments)
        for fund in funds:
            contributed_amount = abs(fund.amount.amount)  # 'abs' because credits have a negative value
            logger.info('assign-funds-to-invoice.assigning-fund',
                        invoice_id=invoice_id,
                        fund_type=type(fund).__name__,
                        fund_id=str(fund.pk),
                        contributed_amount=contributed_amount)
            fund.invoice_id = invoice_id
            fund.save()
            invoice_due_amount -= contributed_amount
            if invoice_due_amount <= 0:
                break

    #
    # 2. Mark invoice paid if nothing is due.
    #
    if invoice_due_amount <= 0:
        logger.info('assign-funds-to-invoice.mark-paid', invoice_id=invoice_id, invoice_due_amount=invoice_due_amount)
        invoice.status = Invoice.PAID
        invoice.save()

    #
    # 3. Carry forward any overpaid money.
    #
    if invoice_due_amount < 0:
        overpayment = Money(abs(invoice_due_amount), invoice_due_currency)
        logger.info('assign-funds-to-invoice.handling-overpayment',
                    invoice_id=invoice_id,
                    overpayment=overpayment)
        with transaction.atomic():
            Charge.objects.create(account_id=account_id, amount=overpayment, product_code=CARRIED_FORWARD,
                                  invoice_id=invoice_id)
            Charge.objects.create(account_id=account_id, amount=-overpayment, product_code=CREDIT_REMAINING)

    return invoice.status == Invoice.PAID


def get_accounts_which_delinquent_status_has_to_change(
    account_ids: List[int],
    unpaid_invoices_threshold: Optional[int],
    days_since_last_unpaid_threshold: Optional[int],
    currency_amount_threshold_map: Optional[dict],
) -> Tuple[Dict[int, List[str]], List[int]]:
    """
    Gets a summary of accounts which delinquent status have to be updated
    :param account_ids: List of account ids to be evaluated
    :param unpaid_invoices_threshold: Number of unpaid invoices to consider an account
                                      as delinquent
    :param days_since_last_unpaid_threshold: Days to take into account since the last
                                             unpaid invoice to consider an account as
                                             delinquent
    :param currency_amount_threshold_map: Balance threshold to consider an account as
                                          delinquent.
                                          Ex: {'CHF': 200, 'EUR': 100, 'NOK': 150}
    :return: (
        New delinquent accounts and reason map. Ex: {111: ['Reason why', ...], ...},
        New compliant accounts ids list
    )
    """
    accounts = Account.objects.filter(id__in=account_ids)
    new_delinquent_accounts_map = {}
    new_compliant_accounts_ids = []
    for account in accounts:
        reasons = compute_account_violations(
            account,
            unpaid_invoices_threshold,
            days_since_last_unpaid_threshold,
            currency_amount_threshold_map,
        )

        if not account.delinquent and reasons:
            new_delinquent_accounts_map[account.id] = reasons

        elif account.delinquent and not reasons:
            new_compliant_accounts_ids.append(account.id)

    return new_delinquent_accounts_map, new_compliant_accounts_ids


def compute_account_violations(
    account: Account,
    unpaid_invoices_threshold: Optional[int],
    days_since_last_unpaid_threshold: Optional[int],
    currency_amount_threshold_map: Optional[dict],
) -> List[str]:
    """
    Check if an account has to be marked as delinquent
    :return: Reasons why account has to be marked as delinquent
    """
    reasons = []
    pending_invoices = account.invoices.filter(status=Invoice.PENDING)
    if (
        unpaid_invoices_threshold is not None
        and pending_invoices.count() >= unpaid_invoices_threshold
    ):
        reasons.append(
            f'Account has more than {unpaid_invoices_threshold} pending invoices'
        )

    if days_since_last_unpaid_threshold is not None and pending_invoices:
        last_pending_invoice = pending_invoices.last()
        days_since_last_pending_invoice = (
            (date.today() - last_pending_invoice.due_date).days
        )
        if days_since_last_pending_invoice >= days_since_last_unpaid_threshold:
            reasons.append(
                f'Account has a debt since more than '
                f'{days_since_last_unpaid_threshold} days'
            )

    if currency_amount_threshold_map:
        account_balance = account.balance()
        for amount_due in account_balance.monies():
            currency = str(amount_due.currency)
            if (
                amount_due.amount < 0
                and currency in currency_amount_threshold_map
                and abs(amount_due.amount) > currency_amount_threshold_map[currency]
            ):
                reasons.append(
                    f'Account has a debt of more than {abs(amount_due.amount)} '
                    f'{currency}'
                )

    return reasons


def toggle_delinquent_status(account_ids: List[int]):
    """
    Toggle delinquent status of each account
    """
    Account.objects.filter(id__in=account_ids).update(delinquent=Case(
        When(delinquent=True, then=Value(False)),
        default=Value(True)
    ))
