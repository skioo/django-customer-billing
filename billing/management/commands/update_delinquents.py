import json
import logging
from datetime import datetime
from typing import List

from django.core.management.base import BaseCommand

from ...models import Account, Invoice

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
        'This command mark accounts as delinquent and vice versa when some criterias '
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
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Shows a summary of accounts which will be marked as delinquent.'
        )

    def handle(self, *args, **options):
        unpaid_invoices_threshold = options['unpaid_invoices']
        days_since_last_unpaid_threshold = options['days_since_last_unpaid']
        currency_amount_threshold_map = options['amount_thresholds']

        new_delinquent_accounts_ids = self.get_new_delinquent_accounts_ids(
            unpaid_invoices_threshold,
            days_since_last_unpaid_threshold,
            currency_amount_threshold_map,
        )
        new_legal_accounts_ids = self.get_new_legal_accounts_ids(
            unpaid_invoices_threshold,
            days_since_last_unpaid_threshold,
            currency_amount_threshold_map,
        )

        self.show_accounts_summary(
            'ACCOUNTS TO BE MARKED AS DELINQUENT',
            new_delinquent_accounts_ids,
        )
        self.show_accounts_summary(
            'ACCOUNTS TO BE MARKED AS LEGAL AGAIN',
            new_legal_accounts_ids,
        )

        if not options['dry_run']:
            n_delinquent_accounts = Account.objects.filter(
                id__in=new_delinquent_accounts_ids,
            ).update(delinquent=True)
            logger.info(f'Number of new delinquent accounts: {n_delinquent_accounts}')
            n_legal_accounts = Account.objects.filter(
                id__in=new_legal_accounts_ids,
            ).update(delinquent=False)
            logger.info(f'Number of legalized accounts: {n_legal_accounts}')

    def get_new_delinquent_accounts_ids(
        self,
        unpaid_invoices_threshold: int,
        days_since_last_unpaid_threshold: int,
        currency_amount_threshold_map: dict,
    ) -> List[int]:
        legal_accounts = Account.objects.filter(delinquent=False)
        new_delinquent_accounts_ids = []
        for account in legal_accounts:
            if self.account_hast_to_be_marked_as_delinquent(
                account,
                unpaid_invoices_threshold,
                days_since_last_unpaid_threshold,
                currency_amount_threshold_map,
            ):
                new_delinquent_accounts_ids.append(account.id)
        return new_delinquent_accounts_ids

    def get_new_legal_accounts_ids(
        self,
        unpaid_invoices_threshold: int,
        days_since_last_unpaid_threshold: int,
        currency_amount_threshold_map: dict,
    ) -> List[int]:
        delinquent_accounts = Account.objects.filter(delinquent=False)
        new_legal_accounts_ids = []
        for account in delinquent_accounts:
            if not self.account_hast_to_be_marked_as_delinquent(
                account,
                unpaid_invoices_threshold,
                days_since_last_unpaid_threshold,
                currency_amount_threshold_map,
            ):
                new_legal_accounts_ids.append(account.id)
        return new_legal_accounts_ids

    @staticmethod
    def account_hast_to_be_marked_as_delinquent(
        account: Account,
        unpaid_invoices_threshold: int,
        days_since_last_unpaid_threshold: int,
        currency_amount_threshold_map: dict,
    ):
        account_balance = account.balance()
        if account_balance == 0:
            return False

        pending_invoices = account.invoices.filter(status=Invoice.PENDING)
        if pending_invoices.count() > unpaid_invoices_threshold:
            return True

        if (
            pending_invoices
            and (
                (datetime.now() - pending_invoices.last().created).days
                > days_since_last_unpaid_threshold
            )
        ):
            return True

        if (
            account.currency in currency_amount_threshold_map.keys
            and account_balance > currency_amount_threshold_map[account.currency]
        ):
            return True

        return False

    @staticmethod
    def show_accounts_summary(header: str, account_ids: List[int]):
        logger.info(header)
        accounts = Account.objects.filter(id__in=account_ids)
        for account in accounts:
            logger.info(f'[{account.id}] {account.owner}')
