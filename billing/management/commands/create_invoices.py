import logging
from datetime import timedelta, date

import progressbar
import structlog
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.utils import timezone, dateparse

from ...actions.accounts import create_invoices
from ...models import Account


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


def parse_due_date(s):
    d = dateparse.parse_date(s)
    if d is None:
        raise ('Not a valid iso8601 date: {}'.format(s))
    return d


class Command(BaseCommand):
    help = """Create invoices for all the accounts that have pending charges.
              Pass -v 2 to see sql queries.
              """

    def add_arguments(self, parser):
        parser.add_argument('--quiet-days', type=int, required=True,
                            help='Accounts with charges that appeared since quiet-days will not be invoiced. '
                                 '0 means invoice all.')
        parser.add_argument('--due-date', type=parse_due_date, default=date.today(),
                            help='The due date of the invoices that are created. Defaults to today')
        parser.add_argument('--dry-run', action='store_true',
                            help='Counts the accounts that will be invoiced and exits')
        parser.add_argument('--progress', action='store_true', help='Displays a progress bar')

    def handle(self, *args, **options):
        if options['verbosity'] >= 2:
            set_debug('django.db.backends')

        accounts = Account.objects.open().with_uninvoiced_positive_charges()

        quiet_days = options['quiet_days']
        if quiet_days != 0:
            dt = timezone.now() - timedelta(days=quiet_days)
            accounts = accounts.with_no_charges_since(dt)

        dry_run = options['dry_run']
        due_date = options['due_date']

        logger.info('create-invoices-start', dry_run=dry_run, quiet_days=quiet_days, due_date=due_date,
                    invoicable_accounts=len(accounts))

        if dry_run:
            return

        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        try:
            stats = defaultdict(lambda: 0)
            for account in accounts:
                try:
                    invoices = create_invoices(account_id=account.pk, due_date=due_date)
                    stats_key = '{}_invoices'.format(len(invoices))
                    stats[stats_key] += 1
                except Exception as ex:
                    logger.error('error', account_id=account.pk, ex=ex)
                    stats['error'] += 1
        finally:
            logger.info('create-invoices-done', **stats)
