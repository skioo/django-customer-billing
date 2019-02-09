from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import charges
from billing.models import Account, Charge, Invoice


class ChargeActionsTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_should_delete_uninvoiced_charge(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF')
        charges.cancel_charge(charge.pk)
        # Check in db
        retrieved = Charge.all_charges.all()[0]
        assert retrieved.deleted

    def test_it_should_create_reversal_credit_for_invoiced_charge(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF',
                                       invoice=invoice)
        charges.cancel_charge(charge.pk)
        # Check in db
        reversal = Charge.objects.exclude(pk=charge.pk).get()
        assert reversal.account == self.account
        assert reversal.amount == Money(-10, 'CHF')
        assert reversal.product_code == 'REVERSAL'
        assert reversal.reverses == charge

    def test_it_should_forbid_cancelling_a_deleted_charge(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF',
                                       deleted=True)
        with raises(charges.ChargeAlreadyCancelledError, match='Cannot cancel deleted charge.'):
            charges.cancel_charge(charge.pk)

    def test_it_should_forbid_cancelling_a_reversed_charge(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF')
        Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), product_code='REVERSAL',
                              reverses=charge)
        with raises(charges.ChargeAlreadyCancelledError, match='Cannot cancel reversed charge.'):
            charges.cancel_charge(charge.pk)
