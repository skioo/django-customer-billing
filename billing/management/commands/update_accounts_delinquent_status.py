import structlog
from django.core.management.base import BaseCommand

from ...actions.accounts import (
    get_accounts_which_delinquent_status_has_to_change,
    toggle_delinquent_status,
)
from ...models import Account
from ...signals import delinquent_status_updated

logger = structlog.get_logger()


class Command(BaseCommand):
    help = (
        'This command mark accounts as delinquent and vice versa when account has '
        'pending invoices'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Shows accounts which delinquent status is going to change'
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

        toggle_delinquent_status(
            new_delinquent_account_ids + new_compliant_account_ids
        )

        if new_delinquent_account_ids or new_compliant_account_ids:
            delinquent_status_updated.send(
                sender=self,
                new_delinquent_account_ids=new_delinquent_account_ids,
                new_compliant_account_ids=new_compliant_account_ids,
            )
