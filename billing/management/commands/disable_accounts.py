import logging
from typing import List

from django.core.management.base import BaseCommand

from ...models import Account

logger = logging.getLogger('django.db.backends')
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    help = """This command disables accounts that are detected as delinquent"""

    def add_arguments(self, parser):
        parser.add_argument('--just-inspect', action='store_true', default=False,
                            help='Shows a summary of accounts which will be disabled.')

    def handle(self, *args, **options):
        accounts = self.get_delinquent_accounts()
        if options['just_inspect']:
            self.show_accounts_summary(accounts)
        else:
            n_disabled_accounts = accounts.update(disabled=True)
            logger.info(f'Number of disabled accounts: {n_disabled_accounts}')

    @staticmethod
    def show_accounts_summary(accounts: List[Account]):
        logger.info('ACCOUNTS TO BE DISABLED')
        for account in accounts:
            logger.info(f'[{account.id}] {account.owner}')

    @staticmethod
    def get_delinquent_accounts():
        """
        TODO: Choose a criteria categorize an account as a delinquent
        """
        return Account.objects.filter(status=Account.OPEN, disabled=False)