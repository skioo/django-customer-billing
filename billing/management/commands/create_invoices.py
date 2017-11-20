import logging
import sys

from django.core.management.base import BaseCommand

from .logging_helper import setup_logging
from ...actions.accounts import create_invoices
from ...models import Account


class Command(BaseCommand):
    help = 'Create invoices for all the accounts that have pending charges'

    def add_arguments(self, parser):
        parser.add_argument('--verbose', action='store_true', dest='verbose')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run')

    def handle(self, *args, **options):
        setup_logging(options['verbose'])

        accounts = Account.open.with_uninvoiced_charges()
        self.stdout.write('{} accounts are invoiceable\n\n'.format(len(accounts)))

        if options['dry_run']:
            return

        stats = Stats()
        try:
            for account in accounts:
                try:
                    invoices = create_invoices(account_id=account.pk)
                    stats.result(account, invoices)
                except Exception:
                    stats.error(account, sys.exc_info()[1])
        finally:
            self.stdout.write(str(stats))


class Stats:
    def __init__(self):
        self._success = 0
        self._no_invoice = 0
        self._error = 0

    def result(self, account, invoices):
        logging.debug('Account %s, generated %s invoices', account, len(invoices))
        if len(invoices) > 0:
            self._success += 1
        else:
            self._no_invoice += 1

    def error(self, account, error):
        logging.error('Account %s, error: %s', account, error)
        self._error += 1

    def __str__(self):
        template = 'Success:       {s._success}\n' \
                   'No invoice:    {s._no_invoice}\n' \
                   'Errors:        {s._error}\n' \
                   'Total:         {total}\n'
        return template.format(s=self, total=self._success + self._no_invoice + self._error)
