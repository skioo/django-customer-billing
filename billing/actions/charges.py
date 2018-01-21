from django.db import transaction
from structlog import get_logger

from .accounts import add_charge
from ..models import Charge

logger = get_logger()

REVERSAL_PRODUCT_CODE = 'REVERSAL'


class ChargeAlreadyCancelledError(Exception):
    pass


def cancel_charge(charge_id: str) -> None:
    """
    Cancels an existing charge.

    If the charge was already cancelled then an Exception is raised.

    If it is not in an invoice then the charge is deleted,
    otherwise a Credit object is created to reverse the Charge.

    :param charge_id: The id of the charge to cancel.
    """
    logger.info('cancelling-charge', charge_id=charge_id)

    with transaction.atomic():
        charge = Charge.all_charges.get(pk=charge_id)

        if charge.deleted:
            raise ChargeAlreadyCancelledError("Cannot cancel deleted charge.")

        if Charge.all_charges.filter(reverses=charge_id).exists():
            raise ChargeAlreadyCancelledError("Cannot cancel reversed charge.")

        if charge.invoice is None:
            charge.deleted = True
            charge.save()
        else:
            add_charge(
                account_id=charge.account_id,
                reverses_id=charge_id,
                amount=-charge.amount,
                product_code=REVERSAL_PRODUCT_CODE)
