import json
import logging

from django.core.management.base import BaseCommand

from ...actions.accounts import mark_accounts_as_legal, mark_accounts_as_delinquent
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
                           --amount-thresholds '{"CHF": 200, "EUR": 100, "NOK": 150}'
    """
    help = (
        'This command mark accounts as delinquent and vice versa when some criteria '
        'are accomplished'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--unpaid-invoices',
            type=int,
            default=2,
            help='Number of unpaid invoices to consider an user as a delinquent'
        )
        parser.add_argument(
            '--days-since-last-unpaid',
            type=int,
            default=2,
            help=(
                'Days to take into account since the last unpaid invoice to consider '
                'an user as a delinquent'
            )
        )
        parser.add_argument(
            '--amount-thresholds',
            type=json.loads,
            help=(
                'Balance threshold to consider an user as a delinquent. '
                'Ex: \'{"CHF": 200, "EUR": 100, "NOK": 150}\''
            )
        )

    def handle(self, *args, **options):
        unpaid_invoices_threshold = options['unpaid_invoices']
        days_since_last_unpaid_threshold = options['days_since_last_unpaid']
        currency_amount_threshold_map = options['amount_thresholds']

        account_ids = Account.objects.values_list('id', flat=True)
        new_delinquent_accounts_ids = mark_accounts_as_delinquent(
            account_ids,
            unpaid_invoices_threshold,
            days_since_last_unpaid_threshold,
            currency_amount_threshold_map,
        )
        account_ids = list(filter(
            lambda account_id: account_id not in new_delinquent_accounts_ids,
            account_ids
        ))
        legalized_accounts_ids = mark_accounts_as_legal(
            account_ids,
            unpaid_invoices_threshold,
            days_since_last_unpaid_threshold,
            currency_amount_threshold_map,
        )

        logger.info(f'New delinquent accounts: {len(new_delinquent_accounts_ids)}')
        logger.info(f'Legalized accounts: {len(legalized_accounts_ids)}')
