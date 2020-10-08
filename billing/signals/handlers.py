from django.dispatch import receiver
from structlog import get_logger

from billing.signals import credit_card_registered, delinquent_status_updated
from ..actions.accounts import charge_pending_invoices
from ..models import EventLog

logger = get_logger()


@receiver(delinquent_status_updated)
def delinquent_status_updated_handler(
    sender,
    new_delinquent_accounts_map=None,
    new_compliant_accounts_ids=None,
    **kwargs
):
    new_delinquent_accounts_map = new_delinquent_accounts_map or {}
    new_compliant_accounts_ids = new_compliant_accounts_ids or []
    logger.info(
        'delinquent-status-updated-handler',
        new_delinquent_accounts=new_delinquent_accounts_map.keys(),
        new_compliant_accounts=new_compliant_accounts_ids,
    )
    EventLog.objects.bulk_create([
        EventLog(
            account_id=account_id,
            type=EventLog.NEW_DELINQUENT,
            text='\n'.join(reasons),
        )
        for account_id, reasons in new_delinquent_accounts_map.items()
    ])
    EventLog.objects.bulk_create([
        EventLog(
            account_id=account_id,
            type=EventLog.NEW_COMPLIANT,
        )
        for account_id in new_compliant_accounts_ids
    ])


@receiver(credit_card_registered)
def credit_card_registered_handler(sender, credit_card, **kwargs):
    account = credit_card.account
    if account.delinquent:
        charge_pending_invoices(account)
