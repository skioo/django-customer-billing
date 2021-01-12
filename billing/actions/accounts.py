"""
State changes for accounts.

Also, the account is the aggregate root for invoices and charges,
so the creation of those is managed here.

"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import DefaultDict, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Sum
from moneyed import Money
from structlog import get_logger

from billing.signals import invoice_ready
from . import invoices
from .invoices import PreconditionError
from ..models import (
    Account, CARRIED_FORWARD, CREDIT_REMAINING, Charge, CreditCard,
    EventLog, Invoice, ProductProperty, Transaction, total_amount,
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
    account_ids: List[UUID]
) -> Tuple[List[UUID], List[UUID]]:
    accounts = Account.objects.filter(id__in=account_ids)
    new_delinquent_account_ids = []
    new_compliant_account_ids = []
    for account in accounts:
        reasons = get_reasons_account_is_violating_delinquent_criteria(account.id)
        if reasons and not account.delinquent:
            new_delinquent_account_ids.append(account.id)
        if not reasons and account.delinquent:
            new_compliant_account_ids.append(account.id)

    return new_delinquent_account_ids, new_compliant_account_ids


def get_reasons_account_is_violating_delinquent_criteria(
    account_id: UUID
) -> List[str]:
    reasons = []
    account = Account.objects.get(id=account_id)
    if account.invoices.filter(status=Invoice.PENDING).count() > 0:
        reasons.append('Account has pending invoices')

    if not CreditCard.objects.filter(account=account).valid().exists():
        reasons.append('Account has not any valid credit card registered')

    return reasons


def mark_account_as_delinquent(account_id: UUID, reason: str):
    account = Account.objects.get(id=account_id)
    if not account.delinquent:
        logger.info('mark-account-as-delinquent', account_id=account_id, reason=reason)
        account.delinquent = True
        account.save()
        EventLog.objects.create(
            account_id=account_id,
            type=EventLog.NEW_DELINQUENT,
            text=reason,
        )


def mark_account_as_compliant(account_id: UUID, reason: str):
    account = Account.objects.get(id=account_id)
    if account.delinquent:
        logger.info('mark-account-as-compliant', account_id=account_id, reason=reason)
        account.delinquent = False
        account.save()
        EventLog.objects.create(
            account_id=account_id,
            type=EventLog.NEW_COMPLIANT,
            text=reason,
        )


def charge_pending_invoices(account_id: UUID) -> Dict[str, int]:
    account = Account.objects.get(id=account_id)
    pending_invoices = account.invoices.payable().only('pk')
    logger.info('charge-pending-invoices', pending_invoices=pending_invoices)

    payment_transactions = []
    for invoice in pending_invoices:
        try:
            payment_transaction = invoices.pay_with_account_credit_cards(invoice.pk)
            if payment_transaction:
                payment_transactions.append(payment_transaction)
        except PreconditionError:
            continue

    reasons = get_reasons_account_is_violating_delinquent_criteria(account.id)
    if not reasons:
        mark_account_as_compliant(account.id, reason='Pending invoices have been paid')

    num_paid_invoices = len(payment_transactions)
    return {
        'num_paid_invoices': num_paid_invoices,
        'num_failed_invoices': len(pending_invoices) - num_paid_invoices
    }


def get_account_valid_credit_card_map(
    billing_account_ids: List[UUID]
) -> DefaultDict[UUID, bool]:
    """
    Returns a map with a boolean which indicates if the account has an active and valid
    credit card with which to pay
    {
        '<account_id_1>': True,
        '<account_id_2>': False
        ...
    }
    """
    acount_valid_cc_map = defaultdict(bool)
    objs = CreditCard.objects.filter(
        account_id__in=billing_account_ids,
        status=CreditCard.ACTIVE
    ).valid().values('account_id').annotate(n_valid_credit_cards=Count('id'))
    for obj in objs:
        acount_valid_cc_map[obj['account_id']] = bool(obj['n_valid_credit_cards'])
    return acount_valid_cc_map


def get_account_balance_map(
    billing_account_ids: List[UUID]
) -> DefaultDict[UUID, DefaultDict[str, Decimal]]:
    """
    Returns a map with the currency balances for each account
    {
        '<account_id_1>': {
            'CHF': 10.,
            'EUR': -20.,
            'NOK': 0.
        },
        ...
    }
    """
    account_charges_map = defaultdict(lambda: defaultdict(Decimal))  # type: DefaultDict

    for obj in Transaction.successful.filter(
        account_id__in=billing_account_ids
    ).values('account_id', 'amount_currency').annotate(sum=Sum('amount')):
        account_charges_map[obj['account_id']][obj['amount_currency']] += obj['sum']

    for obj in Charge.objects.filter(
        account_id__in=billing_account_ids
    ).values('account_id', 'amount_currency').annotate(sum=Sum('amount')):
        account_charges_map[obj['account_id']][obj['amount_currency']] -= obj['sum']

    return account_charges_map
