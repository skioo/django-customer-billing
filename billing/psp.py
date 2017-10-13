from django.core.validators import RegexValidator
from moneyed import Money

from typing import Tuple


#############################################
# The Client API

def charge_credit_card(credit_card_psp_uri: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
    """
    :param credit_card_psp_path: a string representing the credit card in the psp
    :param amount: the amount to charge
    :param client_ref: a reference that will appear on the customer's credit card report
    :return: a tuple (success, payment_psp_uri)
    """
    scheme, credit_card_psp_path = _parse_uri(credit_card_psp_uri)
    success, payment_psp_path = psp_for_scheme(scheme).charge_credit_card(credit_card_psp_path, amount, client_ref)
    return success, _unparse_uri(scheme, payment_psp_path)


def refund_payment(payment_psp_uri: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
    """
    :param payment_psp_uri: a string representing the original payment in the psp
    :param amount: the amount to refund
    :param client_ref: a reference that will appear on the customer's credit card statement
    :return: a tuple (success, refund_psp_uri)
    """
    scheme, payment_psp_path = _parse_uri(payment_psp_uri)
    success, refund_psp_path = psp_for_scheme(scheme).refund_payment(payment_psp_path, amount, client_ref)
    return success, _unparse_uri(scheme, refund_psp_path)


#############################################
# Model support

psp_uri_validator = RegexValidator(r'^\w+:(\w+/)*\w+')


#############################################
# Admin integration


def admin_url(object_psp_uri: str) -> str:
    scheme, object_psp_path = _parse_uri(object_psp_uri)
    return psp_for_scheme(scheme).admin_url(object_psp_path)


#############################################
# The SPI


class PSP:
    """ Each PSP must implement these methods. """

    def admin_url(self, object_psp_path: str) -> str:
        """
        :param object_psp_path: a string representing the object in the psp
        :return:  an url to the admin detail page of the object
        """

    def charge_credit_card(self, credit_card_psp_path: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
        """
        :param credit_card_psp_path: a string representing the credit card in the psp
        :param amount: the amount to charge
        :param client_ref: a reference that will appear on the customer's credit card statement
        :return: a tuple (success, payment_psp_path)
        """
        pass

    def refund_payment(self, payment_psp_path: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
        """
        :param payment_psp_path: a string representing the original payment in the psp
        :param amount: the amount to refund
        :param client_ref: a reference that will appear on the customer's credit card statement
        :return: a tuple (success, refund_psp_path)
        """
        pass

    class Meta:
        abstract = True


def register(scheme: str, psp: PSP) -> None:
    _registry[scheme] = psp


def unregister(scheme: str) -> None:
    """
    Raises NotRegistered if the scheme is not registered
    """
    _ensure_registered(scheme)
    del _registry[scheme]


def psp_for_scheme(scheme: str) -> PSP:
    _ensure_registered(scheme)
    return _registry[scheme]


#############################################
# Internals


def _parse_uri(psp_uri: str) -> Tuple[str, str]:
    scheme, path = psp_uri.split(':', 1)  # Ensure we have two parts
    return scheme, path


def _unparse_uri(scheme: str, path: str) -> str:
    return '{}:{}'.format(scheme, path)


def _ensure_registered(scheme: str) -> None:
    if scheme not in _registry:
        raise Exception("No PSP registered for scheme '{}'".format(scheme))


_registry = {}  # type: ignore
