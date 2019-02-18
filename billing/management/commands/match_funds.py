import logging
from collections import defaultdict

import progressbar
import structlog
from django.core.management.base import BaseCommand

from ...actions.accounts import assign_funds_to_account_pending_invoices
from ...models import Account


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


class Command(BaseCommand):
    help = """For all accounts with pending invoices: tries to match unassigned funds to invoices.
              Pass -v 2 to see sql queries.
              """

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Counts the accounts with pending invoices and exit')
        parser.add_argument('--progress', action='store_true', help='Displays a progress bar')

    def handle(self, *args, **options):
        if options['verbosity'] >= 2:
            set_debug('django.db.backends')

        accounts = Account.objects.open().with_pending_invoices().only('id')

        dry_run = options['dry_run']

        logger.info('match-funds-start', dry_run=dry_run, accounts_with_pending_invoices=len(accounts))

        if dry_run:
            return

        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        try:
            stats = defaultdict(lambda: 0)
            for account in accounts:
                try:
                    paid_invoices = assign_funds_to_account_pending_invoices(account_id=account.id)
                    stats_key = '{}_invoices'.format(len(paid_invoices))
                    stats[stats_key] += 1
                except Exception as ex:
                    logger.error('error', account_id=account.pk, ex=ex)
                    stats['error'] += 1
        finally:
            logger.info('match-funds-done', **stats)
