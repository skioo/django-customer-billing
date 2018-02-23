"""
State changes for accounts.

Also, the account is the aggregate root for invoices and charges,
so the creation of those is managed here.

"""
from datetime import date
from typing import Dict, Optional, Sequence

from django.db import transaction
from moneyed import Money
from structlog import get_logger

from ..models import Account, Charge, Invoice, ProductProperty

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
    Creates the invoices for any uninvoiced charges in the account.
    Creates one invoice per currency (only when the total in that currency is positive).

    :param account_id: The account to invoice.
    :return: A possibly-empty list of Invoices.
    """
    invoices = []
    with transaction.atomic():
        ucs, total = Charge.objects.uninvoiced_with_total(account_id=account_id)
        for amount_due in total.monies():
            if amount_due.amount > 0:
                invoice = Invoice.objects.create(account_id=account_id, due_date=due_date)
                Charge.objects. \
                    uninvoiced_in_currency(account_id=account_id, currency=amount_due.currency) \
                    .update(invoice=invoice)
                invoices.append(invoice)
    logger.info('created-invoices', account_id=str(account_id), invoice_ids=[i.pk for i in invoices])
    return invoices


def add_charge(account_id: str, amount: Money,
               reverses_id: Optional[str] = None,
               product_code: Optional[str] = None,
               product_properties: Optional[Dict[str, str]] = None) -> Charge:
    """
    Add a charge to the account.

    :param account_id: The account on which to add the charge
    :param amount:  The amount of the charge
    :param product_code: A code identifying the type of product cnarged
    :param product_properties: A dict of hames and values.
    :param ad_hoc_label:
    :return: The newly created charge
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
