import logging
from datetime import timedelta
from typing import Sequence

import progressbar
import structlog
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ...actions.accounts import create_invoices
from ...models import Account, Invoice


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


class Command(BaseCommand):
    help = """Create invoices for all the accounts that have pending charges.
              Pass -v 2 to see sql queries.
              """

    def add_arguments(self, parser):
        parser.add_argument('--quiet-days', type=int, default=0,
                            help='Accounts with charges that appeared since quiet-days will not be invoiced')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                            help="Goes thru the motions but doesn't create invoices in the database")
        parser.add_argument('--progress', action='store_true', dest='progress',
                            help='Displays a progress bar')

    def handle(self, *args, **options):
        if options['verbosity'] >= 2:
            set_debug('django.db.backends')

        accounts = Account.objects.open().with_uninvoiced_positive_charges()

        quiet_days = options['quiet_days']
        if quiet_days != 0:
            dt = timezone.now() - timedelta(days=quiet_days)
            accounts = accounts.with_no_charges_since(dt)

        dry_run = options['dry_run']
        logger.info('create-invoices-start', dry_run=dry_run, quiet_days=quiet_days,
                    accounts_with_uninvoiced_charges=len(accounts))

        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        try:
            stats = defaultdict(lambda: 0)
            for account in accounts:
                try:
                    if dry_run:
                        invoices = pretend_to_create_invoices(account_id=account.pk)
                    else:
                        invoices = create_invoices(account_id=account.pk)
                    stats_key = '{}_invoices'.format(len(invoices))
                    stats[stats_key] += 1
                except Exception as ex:
                    logger.error('error', account_id=account.pk, ex=ex)
                    stats['error'] += 1
        finally:
            logger.info('create-invoices-done', **stats)


def pretend_to_create_invoices(account_id: str) -> Sequence[Invoice]:
    with transaction.atomic():
        invoices = create_invoices(account_id=account_id)
        transaction.set_rollback(True)
    return invoices
