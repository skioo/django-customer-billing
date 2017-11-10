from django.db.models import Model
from moneyed import Money
from structlog import get_logger
from typing import List, Tuple

logger = get_logger()


#############################################
# The Client API

class PreconditionError(Exception):
    pass


def charge_credit_card(credit_card_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
    """
    :param credit_card_psp_object: an instance representing the credit card in the psp
    :param amount: the amount to charge
    :param client_ref: a reference that will appear on the customer's credit card report
    :return: a tuple (success, payment_psp_object)
    """
    logger.debug('charge-credit-card', credit_card_psp_object=credit_card_psp_object, amount=amount,
                 client_ref=client_ref)
    if amount.amount <= 0:
        raise PreconditionError('Can only charge positive amounts')
    psp = psp_for_model_instance(credit_card_psp_object)
    return psp.charge_credit_card(credit_card_psp_object, amount, client_ref)


def refund_payment(payment_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
    """
    :param payment_psp_object: an instance representing the original payment in the psp
    :param amount: the amount to refund
    :param client_ref: a reference that will appear on the customer's credit card statement
    :return: a tuple (success, refund_psp_object)
    """
    logger.debug('refund-payment', payment_psp_object=payment_psp_object, amount=amount, client_ref=client_ref)
    if amount.amount <= 0:
        raise PreconditionError('Can only refund positive amounts')
    psp = psp_for_model_instance(payment_psp_object)
    return psp.refund_payment(payment_psp_object, amount, client_ref)


#############################################
# The SPI


class PSP:
    """ Each PSP must implement these methods. """

    def model_classes(self) -> List[Model]:
        """
        :return: the list of model classes that this psp is responsible for.
        """
        pass

    def charge_credit_card(self, credit_card_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
        """
        :param credit_card_psp_object: an instance representing the credit card in the psp
        :param amount: the amount to charge
        :param client_ref: a reference that will appear on the customer's credit card report
        :return: a tuple (success, payment_psp_object)
        """
        pass

    def refund_payment(self, payment_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
        """
        :param payment_psp_object: an instance representing the original payment in the psp
        :param amount: the amount to refund
        :param client_ref: a reference that will appear on the customer's credit card statement
        :return: a tuple (success, refund_psp_object)
        """
        pass

    class Meta:
        abstract = True


#############################################
# The registry

def register(psp: PSP) -> None:
    for model_class in psp.model_classes():
        _registry[model_class] = psp


def unregister(psp: PSP) -> None:
    for model_class in psp.model_classes():
        del _registry[model_class]


def psp_for_model_instance(model_instance: Model) -> PSP:
    model_class = type(model_instance)
    psp = _registry.get(model_class, None)
    if not psp:
        raise Exception("No PSP registered for model class '{}'".format(model_class))
    return psp


_registry = {}  # type: ignore
