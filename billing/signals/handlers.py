from billing_datatrans.signals import credit_card_registered
from django.dispatch import receiver
from structlog import get_logger

from billing.signals import new_delinquents
from ..models import EventLog
from ..actions import invoices

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


@receiver(credit_card_registered)
def credit_card_registered_handler(sender, **kwargs):
    credit_card = kwargs['credit_card']
    print('*' * 50)
    print(credit_card)
    account = credit_card.account
    if account.delinquent:
        pending_invoices_ids = account.invoices.payable().only('pk')
        logger.info(
            'creditcard-registered-handler',
            pending_invoices_ids=pending_invoices_ids
        )
        payments = []
        for invoice_id in pending_invoices_ids:
            payment = invoices.pay_with_account_credit_cards(invoice_id)
            payments.append(payment)
        if len(payments) == len(pending_invoices_ids):
            account.mark_as_compliant()

