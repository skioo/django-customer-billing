import logging
from typing import List

from django.core.management.base import BaseCommand

from ...models import Account

logger = logging.getLogger('django.db.backends')
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    help = (
        'This command mark accounts as delinquent and vice versa when some criterias '
        'are accomplished'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--just-inspect',
            action='store_true',
            default=False,
            help='Shows a summary of accounts which will be marked as delinquent.'
        )

    def handle(self, *args, **options):
        new_delinquent_accounts = self.get_new_delinquent_accounts()
        new_legal_accounts = self.get_new_legal_accounts()
        if options['just_inspect']:
            self.show_accounts_summary(
                'ACCOUNTS TO BE MARKED AS DELINQUENT',
                new_delinquent_accounts
            )
            self.show_accounts_summary(
                'ACCOUNTS TO BE MARKED AS LEGAL AGAIN',
                new_delinquent_accounts
            )
        else:
            n_delinquent_accounts = new_delinquent_accounts.update(delinquent=True)
            logger.info(f'Number of new delinquent accounts: {n_delinquent_accounts}')
            n_legal_accounts = new_legal_accounts.update(delinquent=False)
            logger.info(f'Number of legalized accounts: {n_legal_accounts}')

    @staticmethod
    def show_accounts_summary(header: str, accounts: List[Account]):
        logger.info(header)
        for account in accounts:
            logger.info(f'[{account.id}] {account.owner}')

    @staticmethod
    def get_new_delinquent_accounts():
        """
        TODO: Choose a criteria categorize an account as a delinquent
        """
        return Account.objects.filter(status=Account.OPEN, delinquent=False)

    @staticmethod
    def get_new_legal_accounts():
        """
        TODO: Choose a criteria categorize an account as a delinquent
        """
        return Account.objects.filter(status=Account.OPEN, delinquent=True)
