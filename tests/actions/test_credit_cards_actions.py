from django.contrib.auth.models import User
from django.test import TestCase
from pytest import raises

from billing.actions import credit_cards
from billing.models import Account, CreditCard
from ..models import MyPSPCreditCard


class CreditCardActionsTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        self.cc = CreditCard.objects.create(account=account, type='VIS',
                                            number='1111', expiry_month=12, expiry_year=30,
                                            psp_object=psp_credit_card)

    def test_it_should_deactivate_a_credit_card(self):
        credit_cards.deactivate(self.cc.id)

    def test_it_cannot_deactivate_an_inactive_credit_card(self):
        self.cc.status = CreditCard.INACTIVE
        self.cc.save()
        with raises(Exception):
            credit_cards.deactivate(self.cc.id)

    def test_it_should_reactivate_a_credit_card(self):
        self.cc.status = CreditCard.INACTIVE
        self.cc.save()
        credit_cards.reactivate(self.cc.id)

    def test_it_cannot_reactivate_an_active_credit_card(self):
        with raises(Exception):
            credit_cards.reactivate(self.cc.id)
