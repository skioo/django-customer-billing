from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import accounts
from billing.models import Account, Charge
from billing.signals import invoice_ready
from billing.total import Total
from ..helper import catch_signal


class AccountActionsTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_should_add_charge(self):
        with self.assertNumQueries(4):
            accounts.add_charge(
                account_id=self.account.id,
                amount=Money(10, 'CHF'),
                product_code='PRODUCTA',
                product_properties={'color': 'blue', 'fabric': 'cotton', 'size': 'M'})

        # Now verify what's been written to the db
        retrieved = Charge.objects.all()[0]
        product_properties_dict = {p.name: p.value for p in retrieved.product_properties.all()}
        assert product_properties_dict == {
            'color': 'blue',
            'fabric': 'cotton',
            'size': 'M'
        }

    def test_it_cannot_create_charge_without_label_or_product_code(self):
        with raises(ValidationError):
            accounts.add_charge(account_id=self.account.id, amount=Money(10, 'CHF'))

    def test_it_should_not_add_charge_if_invalid_property_name(self):
        with raises(ValidationError):
            accounts.add_charge(
                account_id=self.account.id,
                amount=Money(10, 'CHF'),
                product_code='PRODUCTA',
                product_properties={'123': 'blue'})

    def test_it_should_not_create_invoice_when_money_is_owed_to_the_user(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-30, 'CHF'), product_code='ACREDIT')
        assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

    def test_it_should_not_create_an_invoice_when_no_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), product_code='ACREDIT')
        with catch_signal(invoice_ready) as signal_handler:
            assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        assert signal_handler.call_count == 0

    def test_it_should_create_an_invoice_when_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-3, 'CHF'), product_code='ACREDIT')

        with catch_signal(invoice_ready) as signal_handler:
            invoices = accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        assert signal_handler.call_count == 1
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.due() == Total(7, 'CHF')
        assert invoice.items.count() == 2

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

    def test_it_should_handle_multicurrency_univoiced_charges(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF')
        Charge.objects.create(account=self.account, amount=Money(30, 'EUR'), product_code='30EURO')

        with catch_signal(invoice_ready) as signal_handler:
            invoices = accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        assert signal_handler.call_count == 2

        assert len(invoices) == 2

        # For some reason the output is always sorted. This makes asserting easy
        invoice1 = invoices[0]
        items1 = invoice1.items.all()
        assert len(items1) == 1
        assert items1[0].product_code == '10CHF'
        assert invoice1.due().currencies() == ['CHF']

        invoice2 = invoices[1]
        items2 = invoice2.items.all()
        assert len(items2) == 1
        assert items2[0].product_code == '30EURO'
        assert invoice2.due().currencies() == ['EUR']

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
