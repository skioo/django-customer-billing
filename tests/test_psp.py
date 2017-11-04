from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.psp import PreconditionError, charge_credit_card, refund_payment, register, unregister
from .my_psp import MyPSP


class PSPTest(TestCase):
    def setUp(self):
        register('test', MyPSP())

    def tearDown(self):
        unregister('test')

    def test_it_should_charge_credit_card_with_the_registered_psp(self):
        success, payment_psp_uri = charge_credit_card('test:1234', Money(10, 'CHF'), 'a charge')
        assert success
        assert payment_psp_uri == 'test:payment/1234'

    def test_it_should_forbid_charging_nonpositive_amounts(self):
        with raises(PreconditionError, match='Can only charge positive amounts'):
            charge_credit_card('test:1234', Money(-10, 'CHF'), 'a charge')

    def test_it_should_refund_payment_with_the_registered_psp(self):
        success, refund_psp_uri = refund_payment('test:1234', Money(3, 'CHF'), 'a refund')
        assert success
        assert refund_psp_uri == 'test:refund/2345'

    def test_it_should_forbid_refunding_nonpositive_amounts(self):
        with raises(PreconditionError, match='Can only refund positive amounts'):
            refund_payment('test:1234', Money(-10, 'CHF'), 'a charge')

    def test_it_should_fail_when_no_registered_psp_for_scheme(self):
        with raises(Exception, match="No PSP registered for scheme 'unknown'"):
            charge_credit_card('unknown:1234', Money(10, 'CHF'), 'a charge')
