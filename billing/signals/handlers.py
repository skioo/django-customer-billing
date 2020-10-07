from django.dispatch import receiver
from structlog import get_logger

from billing.signals import delinquent_status_updated
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
