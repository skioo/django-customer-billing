from django.db.models import Model
from moneyed import Money
from typing import Tuple

from billing.psp import PSP
from .models import MyPSPCreditCard, MyPSPPayment, MyPSPRefund


class MyPSP(PSP):
    def model_classes(self):
        return [MyPSPPayment, MyPSPCreditCard]

    def charge_credit_card(self, credit_card_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
        payment = MyPSPPayment.objects.create(payment_ref='payment_12345')
        return True, payment

    def refund_payment(self, payment_psp_object: Model, amount: Money, client_ref: str) -> Tuple[bool, Model]:
        refund = MyPSPRefund.objects.create(refund_ref='refund_12345')
        return True, refund
