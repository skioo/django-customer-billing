from django.dispatch import receiver
from structlog import get_logger

from billing.signals import new_delinquents
from ..models import EventLog

logger = get_logger()


@receiver(new_delinquents)
def new_delinquents_handler(sender, **kwargs):
    new_delinquent_accounts_map = kwargs['new_delinquent_accounts_map']
    logger.info(
        'new-delinquents-handler',
        new_delinquent_accounts_map=new_delinquent_accounts_map
    )
    EventLog.objects.bulk_create([
        EventLog(
            account_id=account_id,
            type=EventLog.NEW_DELINQUENT,
            text='\n'.join(reasons)
        )
        for account_id, reasons in new_delinquent_accounts_map.items()
    ])
