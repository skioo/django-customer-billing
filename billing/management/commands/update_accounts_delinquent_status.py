import json

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
    """
    Execution example:
        > python manage.py update_delinquents
                           --unpaid-invoices 2
                           --days-since-last-unpaid 30
                           --amount-thresholds '{"CHF": 200, "EUR": 100, "NOK": 1000}'
    """
    help = (
        'This command mark accounts as delinquent and vice versa when some criteria '
        'are accomplished'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--unpaid-invoices',
            type=int,
            default=1,
            help='Number of unpaid invoices to consider an account as delinquent'
        )
        parser.add_argument(
            '--days-since-last-unpaid',
            type=int,
            default=None,
            help=(
                'Days to take into account since the last unpaid invoice to consider '
                'an account as delinquent'
            )
        )
        parser.add_argument(
            '--amount-thresholds',
            type=json.loads,
            default=None,
            help=(
                'Balance threshold to consider an account as delinquent. '
                'Ex: \'{"CHF": 200, "EUR": 100, "NOK": 150}\''
            )
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Shows accounts which delinquent status is going to change'
        )

    def handle(self, *args, **options):
        unpaid_invoices_threshold = options['unpaid_invoices']
        days_since_last_unpaid_threshold = options['days_since_last_unpaid']
        currency_amount_threshold_map = options['amount_thresholds']
        dry_run = options['dry_run']
        logger.info(
            'update-delinquents-command',
            unpaid_invoices_threshold=unpaid_invoices_threshold,
            days_since_last_unpaid_threshold=days_since_last_unpaid_threshold,
            currency_amount_threshold_map=currency_amount_threshold_map,
            dry_run=dry_run,
        )

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_accounts_map, new_compliant_accounts_ids = (
            get_accounts_which_delinquent_status_has_to_change(
                account_ids,
                unpaid_invoices_threshold,
                days_since_last_unpaid_threshold,
                currency_amount_threshold_map,
            )
        )

        logger.info(
            'update-delinquents-command',
            new_delinquent_accounts=len(new_delinquent_accounts_map.keys()),
            new_compliant_accounts=len(new_compliant_accounts_ids),
        )
        if dry_run:
            return

        toggle_delinquent_status(
            list(new_delinquent_accounts_map.keys()) + new_compliant_accounts_ids
        )

        if new_delinquent_accounts_map or new_compliant_accounts_ids:
            delinquent_status_updated.send(
                sender=self,
                new_delinquent_accounts_map=new_delinquent_accounts_map,
                new_compliant_accounts_ids=new_compliant_accounts_ids,
            )
