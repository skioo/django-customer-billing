from typing import List
from uuid import UUID

from django.dispatch import receiver
from structlog import get_logger

from billing.signals import delinquent_status_updated
from ..admin import AccountAdmin
from ..models import EventLog

logger = get_logger()


@receiver(delinquent_status_updated)
def delinquent_status_updated_handler(
    sender,
    new_delinquent_account_ids: List[UUID] = None,
    new_compliant_account_ids: List[UUID] = None,
    **kwargs
):
    new_delinquent_account_ids = new_delinquent_account_ids or []
    new_compliant_account_ids = new_compliant_account_ids or []
    logger.info(
        'delinquent-status-updated-handler',
        new_delinquent_accounts=new_delinquent_account_ids,
        new_compliant_accounts=new_compliant_account_ids,
    )

    reason = 'Account has pending invoices'
    if type(sender) == AccountAdmin:
        reason = 'Manually'

    EventLog.objects.bulk_create([
        EventLog(
            account_id=account_id,
            type=EventLog.NEW_DELINQUENT,
            text=reason,
        )
        for account_id in new_delinquent_account_ids
    ])
    EventLog.objects.bulk_create([
        EventLog(
            account_id=account_id,
            type=EventLog.NEW_COMPLIANT,
            text='Account has not pending invoices',
        )
        for account_id in new_compliant_account_ids
    ])
