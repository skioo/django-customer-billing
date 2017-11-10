from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.psp import PreconditionError, charge_credit_card, refund_payment, register, unregister
from .models import MyPSPCreditCard, MyPSPPayment
from .my_psp import MyPSP


class PSPTest(TestCase):
    def setUp(self):
        register(MyPSP())
        self.psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        self.psp_payment = MyPSPPayment.objects.create(payment_ref='apaymentref')

    def tearDown(self):
        unregister(MyPSP())

    def test_it_should_charge_credit_card_with_the_registered_psp(self):
        success, payment_psp_object = charge_credit_card(self.psp_credit_card, Money(10, 'CHF'), 'a charge')
        assert success
        assert payment_psp_object

    def test_it_should_forbid_charging_nonpositive_amounts(self):
        with raises(PreconditionError, match='Can only charge positive amounts'):
            charge_credit_card(self.psp_credit_card, Money(-10, 'CHF'), 'a charge')

    def test_it_should_refund_payment_with_the_registered_psp(self):
        success, refund_psp_object = refund_payment(self.psp_payment, Money(3, 'CHF'), 'a refund')
        assert success
        assert refund_psp_object

    def test_it_should_forbid_refunding_nonpositive_amounts(self):
        with raises(PreconditionError, match='Can only refund positive amounts'):
            refund_payment(self.psp_payment, Money(-10, 'CHF'), 'a charge')

    def test_it_should_fail_when_no_psp_registered(self):
        with raises(Exception, match="No PSP registered for model class '<class 'str'>'"):
            charge_credit_card('a string', Money(10, 'CHF'), 'a charge')
