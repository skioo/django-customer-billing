from django.db.models.signals import post_save
from django.dispatch import receiver
from structlog import get_logger

from billing.models import Account
from billing.signals import update_delinquents_command_executed
from ..models import EventLog

logger = get_logger()


@receiver(update_delinquents_command_executed)
def update_delinquents_command_executed_handler(sender, **kwargs):
    logger.info('Generating logs about new delinquents')
    new_delinquent_accounts_map = kwargs['new_delinquent_accounts_map']
    EventLog.objects.bulk_create([
        EventLog(
            user_id=Account.objects.get(id=billing_account_id).owner_id,
            type=EventLog.NEW_DELINQUENT,
            text='\n'.join(reasons)
        )
        for billing_account_id, reasons in new_delinquent_accounts_map.items()
    ])


@receiver(post_save, sender=Account)
def billing_account_post_save(sender, instance, created, **kwargs):
    update_fields = kwargs.get('update_fields')
    if update_fields and 'delinquent' in update_fields and instance.delinquent:
        EventLog.objects.create(
            user_id=instance.owner_id,
            type=EventLog.NEW_DELINQUENT,
            text='Manually'
        )
