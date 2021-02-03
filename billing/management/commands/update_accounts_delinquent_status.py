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
        'Marks accounts as delinquent and vice versa when account has pending invoices '
        'or not valid credit cards registered.'
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
        logger.info('update-accounts-delinquent-status', dry_run=dry_run)

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_account_ids, new_compliant_account_ids = (
            get_accounts_which_delinquent_status_has_to_change(account_ids)
        )

        logger.info(
            'update-accounts-delinquent-status',
            new_delinquent_accounts=len(new_delinquent_account_ids),
            new_compliant_accounts=len(new_compliant_account_ids),
        )
        if dry_run:
            return

        accounts = Account.objects.filter(id__in=new_delinquent_account_ids)
        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        n_accounts_marked_as_delinquent = 0
        for account in accounts:
            reasons = get_reasons_account_is_violating_delinquent_criteria(account.id)
            mark_account_as_delinquent(account.id, reason='. '.join(reasons))
            n_accounts_marked_as_delinquent += 1

        accounts = Account.objects.filter(id__in=new_compliant_account_ids)
        if options['progress']:
            bar = progressbar.ProgressBar()
            accounts = bar(accounts)

        n_accounts_marked_as_compliant = 0
        for account in accounts:
            mark_account_as_compliant(account.id, reason='Requirements met again')
            n_accounts_marked_as_compliant += 1

        logger.info(
            'update-accounts-delinquent-status',
            n_accounts_marked_as_delinquent=n_accounts_marked_as_delinquent,
            n_accounts_marked_as_compliant=n_accounts_marked_as_compliant,
        )
