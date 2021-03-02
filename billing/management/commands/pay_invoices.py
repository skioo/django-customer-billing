import logging
from collections import defaultdict

import progressbar
import structlog
from django.core.management.base import BaseCommand

from ...actions.invoices import pay_with_account_credit_cards
from ...models import CreditCard, Invoice


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


class Command(BaseCommand):
    help = """Pay pending invoices with credit cards registered on accounts.
              Pass v2 to see sql queries"""

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help="Displays the payable invoices but doesn't perform any action."
        )
        parser.add_argument(
            '--progress',
            action='store_true',
            dest='progress',
            help='Displays a progress bar'
        )
        parser.add_argument(
            '--exclude-reka-ccs',
            action='store_true',
            dest='exclude_reka_ccs',
            help='Temporal option to exclude reka credit cards'
        )

    def handle(self, *args, **options):
        if options['verbosity'] >= 2:
            set_debug('django.db.backends')

        dry_run = options['dry_run']

        all_payable_invoices = Invoice.objects.payable()

        logger.debug(
            'pay-invoice-select',
            dry_run=dry_run,
            payable=len(all_payable_invoices)
        )

        # Should replace by a filter, to run in a single sql query
        invoices = [
            invoice
            for invoice in all_payable_invoices
            if CreditCard.objects.valid().filter(account_id=invoice.account_id).exists()
        ]

        exclude_reka_ccs = options['exclude_reka_ccs']
        logger.info(
            'pay-invoices-start',
            dry_run=dry_run,
            payable_with_valid_cc=len(invoices),
            exclude_reka_ccs=exclude_reka_ccs,
        )

        if dry_run:
            return

        if options['progress']:
            bar = progressbar.ProgressBar()
            invoices = bar(invoices)

        try:
            stats = defaultdict(lambda: 0)
            for invoice in invoices:
                try:
                    maybe_transaction = pay_with_account_credit_cards(
                        invoice.pk,
                        options['exclude_reka_ccs']
                    )
                    if maybe_transaction is not None:
                        stats['success'] += 1
                    else:
                        stats['failure'] += 1
                except Exception as ex:
                    logger.error('pay-invoices-error', invoice_id=invoice.pk, ex=ex)
                    stats['error'] += 1
        finally:
            logger.info('pay-invoices-done', **stats)
