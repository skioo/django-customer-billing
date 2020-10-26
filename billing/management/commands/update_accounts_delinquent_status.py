import progressbar
import structlog
from django.core.management.base import BaseCommand

from ...actions.accounts import (
    get_accounts_which_delinquent_status_has_to_change,
    get_reasons_account_is_violating_delinquent_criteria,
    mark_account_as_compliant,
    mark_account_as_delinquent,
)
from ...models import Account

logger = structlog.get_logger()


class Command(BaseCommand):
    help = (
        'This command mark accounts as delinquent and vice versa when account has '
        'pending invoices or not valid credit cards registered'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Shows accounts which delinquent status is going to change'
        )
        parser.add_argument(
            '--progress',
            action='store_true',
            help='Displays a progress bar'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        logger.info('update-delinquents-command', dry_run=dry_run)

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_account_ids, new_compliant_account_ids = (
            get_accounts_which_delinquent_status_has_to_change(account_ids)
        )

        logger.info(
            'update-delinquents-command',
            new_delinquent_accounts=len(new_delinquent_account_ids),
            new_compliant_accounts=len(new_compliant_account_ids),
        )
        if dry_run:
            return

        accounts = Account.objects.filter(id__in=new_delinquent_account_ids)
        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        for account in accounts:
            reasons = get_reasons_account_is_violating_delinquent_criteria(account.id)
            mark_account_as_delinquent(account.id, reason='. '.join(reasons))

        accounts = Account.objects.filter(id__in=new_compliant_account_ids)
        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        for account in accounts:
            mark_account_as_compliant(account.id, reason='Requirements met again')
