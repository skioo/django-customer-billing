from django.db import transaction
from structlog import get_logger

from ..models import CreditCard

logger = get_logger()


def deactivate(credit_card_id: str) -> None:
    """
    Deactivates a credit card.
    """
    logger.info('deactivating-credit-card', credit_card_id=credit_card_id)
    with transaction.atomic():
        cc = CreditCard.objects.get(pk=credit_card_id)
        cc.deactivate()
        cc.save()


def reactivate(credit_card_id: str) -> None:
    """
    Reactivates a credit card.
    """
    logger.info('reactivating-credit-card', credit_card_id=credit_card_id)
    with transaction.atomic():
        cc = CreditCard.objects.get(pk=credit_card_id)
        cc.reactivate()
        cc.save()
