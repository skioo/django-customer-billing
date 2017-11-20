import logging
import sys

from django.core.management.base import BaseCommand

from .logging_helper import setup_logging
from ...actions.invoices import pay_with_account_credit_cards
from ...models import Invoice


class Command(BaseCommand):
    help = 'Pay pending invoices with credit cards registered on accounts'

    def add_arguments(self, parser):
        parser.add_argument('--verbose', action='store_true', dest='verbose')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run')

    def handle(self, *args, **options):
        setup_logging(options['verbose'])

        invoices = Invoice.objects.payable()
        self.stdout.write('{} invoices are payable\n\n'.format(len(invoices)))

        if options['dry_run']:
            return

        stats = Stats()
        try:
            for invoice in invoices:
                try:
                    maybe_transaction = pay_with_account_credit_cards(invoice.pk)
                    if maybe_transaction is not None:
                        stats.success(invoice)
                    else:
                        stats.failure(invoice)
                except Exception:
                    stats.error(invoice, sys.exc_info()[1])
        finally:
            self.stdout.write(str(stats))


class Stats:
    def __init__(self):
        self._success = 0
        self._failure = 0
        self._error = 0

    def success(self, invoice):
        logging.debug('Invoice %s, payed with cc', invoice)
        self._success += 1

    def failure(self, invoice):
        logging.debug('Invoice %s, payment failure', invoice)
        self._failure += 1

    def error(self, invoice, error):
        logging.error('Invoice %s, error: %s', invoice, error)
        self._error += 1

    def __str__(self):
        template = 'Success:    {s._success}\n' \
                   'Failure:    {s._failure}\n' \
                   'Errors:     {s._error}\n' \
                   'Total:      {total}\n'
        return template.format(s=self, total=self._success + self._failure + self._error)
