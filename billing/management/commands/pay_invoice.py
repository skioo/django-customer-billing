import logging

import structlog
from django.core.management.base import BaseCommand

from ...actions.invoices import pay_with_account_credit_cards
from ...models import Invoice


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


class Command(BaseCommand):
    """
    Command for testing purposes
    """
    help = 'Pay a pending invoice'

    def add_arguments(self, parser):
        parser.add_argument(
            '--invoice-id',
            type=str,
            dest='invoice_id',
            help='Invoice id'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help="Displays the payable invoices but doesn't perform any action."
        )

    def handle(self, *args, **options):
        invoice_id = options['invoice_id']
        try:
            invoice = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist:
            logger.error('pay-invoice-does-not-exist', invoice_id=invoice_id)
            return

        logger.info('pay-invoice', invoice=invoice)
        if options['dry_run']:
            return

        try:
            maybe_transaction = pay_with_account_credit_cards(invoice.pk)
            if maybe_transaction is not None:
                logger.info(
                    'pay-invoice',
                    success=True,
                    transaction=maybe_transaction
                )
            else:
                logger.info('pay-invoice', failure=True)

        except Exception as e:
            logger.error('pay-invoice-error', invoice_id=invoice.pk, e=e)
