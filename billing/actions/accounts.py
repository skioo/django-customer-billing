from django.db import transaction
from structlog import get_logger
from typing import Sequence

from ..models import Account, Charge, Invoice

logger = get_logger()


def close(account: Account) -> None:
    logger.info('closing-account', account=account)
    account.close()
    account.save()


def reopen(account: Account) -> None:
    logger.info('reopening-account', account=account)
    account.reopen()
    account.save()


def create_invoice_if_pending_charges(account_id: str) -> Sequence[Invoice]:
    """
    Creates and returns the invoices for any uninvoiced charges in the account.
    If multiple currencies are involved, then one invoice per currency will be generated.

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
    logger.debug('create-invoices', account_id=account_id, invoice_ids=[i.pk for i in invoices])
    return invoices
