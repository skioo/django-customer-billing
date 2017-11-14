"""
State changes for accounts.

Also, the account is the aggregate root for invoices and charges, so it's responsible for creating those.
"""
from django.db import transaction
from moneyed import Money
from structlog import get_logger
from typing import Sequence

from ..models import Account, Charge, Invoice

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


def create_invoice_if_pending_charges(account_id: str) -> Sequence[Invoice]:
    """
    Creates and returns the invoices for any uninvoiced charges in the account.
    If multiple currencies are involved, then one invoice per currency is generated.

    :param account_id: The account to examine for uninvoiced charges.
    :return: A possibly empty list of Invoice objects.
    """
    invoices = []
    with transaction.atomic():
        ucs, total = Charge.objects.uninvoiced_with_total(account_id=account_id)
        for amount_due in total.monies():
            if amount_due.amount > 0:
                invoice = Invoice.objects.create(account_id=account_id)
                Charge.objects. \
                    uninvoiced_in_currency(account_id=account_id, currency=amount_due.currency) \
                    .update(invoice=invoice)
                invoices.append(invoice)
    logger.info('create-invoices', account_id=account_id, invoice_ids=[i.pk for i in invoices])
    return invoices


def add_charge(account_id: str, amount: Money, description: str) -> Charge:
    """
    Add a charge to the account.

    :param account_id: The account on which to add the charge
    :param amount:  The amount of the charge
    :param description:  The description of the charge
    :return: The newly created charge
    """
    logger.info('adding-charge', account_id=account_id, amount=amount, description=description)
    return Charge.objects.create(account_id=account_id,
                                 amount=amount,
                                 description=description)
