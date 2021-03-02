from typing import Optional

from django.db import transaction
from structlog import get_logger

from .. import psp
from ..models import CreditCard, Invoice, Transaction

logger = get_logger()


class PreconditionError(Exception):
    pass


def pay_with_account_credit_cards(
    invoice_id,
    exclude_reka_ccs=False
) -> Optional[Transaction]:
    """
    Get paid for the invoice, trying the valid credit cards on record for the account.

    If successful attaches the payment to the invoice and marks the invoice as paid.

    :param invoice_id: the id of the invoice to pay.
    :param exclude_reka_ccs: Temporal param to exclude reka credit cards
    :return: A successful transaction, or None if we weren't able to pay the invoice.
    """
    logger.debug('invoice-payment-started', invoice_id=invoice_id)
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

        #
        # Precondition: Invoice should be in a state that allows payment
        #
        if not invoice.in_payable_state:
            raise PreconditionError('Cannot pay invoice with status {}.'.format(invoice.status))

        #
        # Precondition: The due amount must be positive, in a single currency
        #
        due = invoice.due().monies()
        if len(due) == 0:
            raise PreconditionError('Cannot pay empty invoice.')
        if len(due) > 1:
            raise PreconditionError('Cannot pay invoice with more than one currency.')
        amount = due[0]
        if amount.amount <= 0:
            raise PreconditionError('Cannot pay invoice with non-positive amount.')

        #
        # Try valid credit cards until one works. Start with the active ones
        #
        valid_credit_cards = CreditCard.objects.valid().filter(account=invoice.account)
        if exclude_reka_ccs:
            valid_credit_cards = valid_credit_cards.exclude(type='REK')
        valid_credit_cards = valid_credit_cards.order_by('status')
        if not valid_credit_cards:
            raise PreconditionError('No valid credit card on account.')

        for credit_card in valid_credit_cards:
            try:
                success, payment_psp_object = psp.charge_credit_card(
                    credit_card_psp_object=credit_card.psp_object,
                    amount=amount,
                    client_ref=str(invoice_id))
                payment = Transaction.objects.create(
                    account=invoice.account,
                    invoice=invoice,
                    amount=amount,
                    success=success,
                    payment_method=credit_card.type,
                    credit_card_number=credit_card.number,
                    psp_object=payment_psp_object)
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
