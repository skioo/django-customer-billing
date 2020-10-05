import json

import structlog
from django.core.management.base import BaseCommand

from ...actions.accounts import (
    get_accounts_which_delinquent_status_has_to_change,
    swap_delinquent_status,
)
from ...models import Account
from ...signals import update_delinquents_command_executed

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
            default=None,
            help='Number of unpaid invoices to consider an user as a delinquent'
        )
        parser.add_argument(
            '--days-since-last-unpaid',
            type=int,
            default=None,
            help=(
                'Days to take into account since the last unpaid invoice to consider '
                'an user as a delinquent'
            )
        )
        parser.add_argument(
            '--amount-thresholds',
            type=json.loads,
            default=None,
            help=(
                'Balance threshold to consider an user as a delinquent. '
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

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_accounts_map, compliant_accounts_ids = (
            get_accounts_which_delinquent_status_has_to_change(
                account_ids,
                unpaid_invoices_threshold,
                days_since_last_unpaid_threshold,
                currency_amount_threshold_map,
            )
        )

        logger.info(f'New delinquent accounts: {new_delinquent_accounts_map}')
        logger.info(f'Legalized accounts: {compliant_accounts_ids}')

        if dry_run:
            return

        swap_delinquent_status(
            list(new_delinquent_accounts_map.keys()) + compliant_accounts_ids
        )

        update_delinquents_command_executed.send(
            sender=self,
            new_delinquent_accounts_map=new_delinquent_accounts_map,
            compliant_accounts_ids=compliant_accounts_ids
        )
