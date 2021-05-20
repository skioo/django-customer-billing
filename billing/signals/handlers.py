from django.dispatch import receiver
from structlog import get_logger

from . import credit_card_deleted, credit_card_registered
from ..actions import accounts
from ..models import Account, CreditCard

logger = get_logger()


@receiver(credit_card_registered)
def credit_card_registered_handler(sender, credit_card: CreditCard, **kwargs):
    account = credit_card.account
    if not account.delinquent:
        return

    reasons = accounts.get_reasons_account_is_violating_delinquent_criteria(account.id)
    if not reasons:
        accounts.mark_account_as_compliant(
            account.id,
            reason='A valid credit card has been registered'
        )


@receiver(credit_card_deleted)
def credit_card_deleted_handler(sender, account: Account, **kwargs):
    if account.delinquent:
        return

    reasons = accounts.get_reasons_account_is_violating_delinquent_criteria(account.id)
    if reasons:
        accounts.mark_account_as_delinquent(
            account.id,
            reason='Account has not any valid credit card registered'
        )
