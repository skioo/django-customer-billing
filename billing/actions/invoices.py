from django.db import transaction
from django_fsm import can_proceed
from structlog import get_logger
from typing import Union

from .. import psp
from ..models import Invoice, Transaction

logger = get_logger()


class PaymentError(Exception):
    pass


class PreconditionError(PaymentError):
    pass


def pay(invoice_id) -> Union[Transaction, None]:
    """
    Get payed for the invoice, using credit cards on record for the account.

    If successful attaches the payment to the invoice and mark the invoice as payed.

    :param invoice_id: the id of the invoice to pay.
    :return: either None or a successful transaction

    XXX: Better logging of complex objects
    """
    logger.debug('invoice-payment-started', invoice_id=invoice_id)
    # Lock to avoid mutations while paying, and multiple payments of the same invoice
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

        # Invoice should be in a state that allows payment
        if not can_proceed(invoice.pay):
            raise PreconditionError('Invoice not in valid state.')

        # A valid credit card is needed to attempt payment
        credit_cards = invoice.account.credit_cards.all()
        if not credit_cards:
            raise PreconditionError('No credit card on account.')
        valid_credit_cards = [cc for cc in credit_cards if not cc.is_expired()]
        if not valid_credit_cards:
            raise PreconditionError('No valid credit card on account.')

        # The invoice needs a positive total, in a single currency (for now)
        total = invoice.total().monies()
        if len(total) == 0:
            raise PreconditionError('Cannot pay empty invoice.')
        if len(total) > 1:
            raise PreconditionError('Cannot pay invoice with more than one currency.')
        amount = total[0]
        if amount.amount <= 0:
            raise PreconditionError('Cannot pay invoice with non-positive amount.')

        for credit_card in valid_credit_cards:
            try:
                success, payment_psp_uri = psp.charge_credit_card(
                    credit_card_psp_uri=credit_card.psp_uri,
                    amount=amount,
                    client_ref=str(invoice_id))
                payment = Transaction.objects.create(
                    account=invoice.account,
                    invoice=invoice,
                    amount=amount,
                    success=success,
                    payment_method=credit_card.type,
                    credit_card_number=credit_card.number,
                    psp_uri=payment_psp_uri)
                if success:
                    invoice.pay()
                    invoice.save()
                    logger.info('invoice-payment-success', invoice=invoice_id, payment=payment)
                    return payment
                else:
                    logger.info('invoice-payment-failure', invoice=invoice_id, payment=payment)
            except Exception as e:
                logger.error('invoice-payment-error', invoice_id=invoice_id, credit_card=credit_card, exc_info=e)
        return None
