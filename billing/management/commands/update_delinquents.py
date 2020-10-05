import json
import logging
from typing import List, Tuple, Dict

from django.core.management.base import BaseCommand

from ...actions.accounts import update_accounts_delinquent_status
from ...models import Account

logger = logging.getLogger('django.db.backends')
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


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

    def handle(self, *args, **options) -> Tuple[Dict[int, List[str]], List[int]]:
        unpaid_invoices_threshold = options['unpaid_invoices']
        days_since_last_unpaid_threshold = options['days_since_last_unpaid']
        currency_amount_threshold_map = options['amount_thresholds']

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_accounts_map, complaint_accounts_ids = (
            update_accounts_delinquent_status(
                account_ids,
                unpaid_invoices_threshold,
                days_since_last_unpaid_threshold,
                currency_amount_threshold_map,
            )
        )

        logger.info(
            f'New delinquent accounts: {len(new_delinquent_accounts_map.keys())}'
        )
        logger.info(f'Legalized accounts: {len(complaint_accounts_ids)}')

        return new_delinquent_accounts_map, complaint_accounts_ids
