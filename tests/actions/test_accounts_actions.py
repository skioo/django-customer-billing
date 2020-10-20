from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import accounts
from billing.models import Account, Charge, Invoice
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

    def test_it_should_not_create_invoice_no_charges_are_due(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='DELETED', deleted=True)
        Charge.objects.create(account=self.account, amount=Money(30, 'CHF'), product_code='INVOICED', invoice=invoice)
        assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

    def test_it_should_create_an_invoice_when_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-3, 'CHF'), product_code='ACREDIT')

        invoices = accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.total_charges() == Total(10, 'CHF')
        assert invoice.due() == Total(10, 'CHF')
        assert invoice.items.count() == 1

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

    def test_it_should_create_an_invoice_even_when_enough_credit(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-30, 'CHF'), product_code='ACREDIT')
        invoices = accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.total_charges() == Total(10, 'CHF')
        assert invoice.due() == Total(10, 'CHF')
        assert invoice.items.count() == 1

    def test_it_should_handle_multicurrency_univoiced_charges(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF')
        Charge.objects.create(account=self.account, amount=Money(30, 'EUR'), product_code='30EURO')

        invoices = accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

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

    def test_it_should_send_a_signal_when_an_invoice_was_created(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')

        with catch_signal(invoice_ready) as signal_handler:
            accounts.create_invoices(account_id=self.account.pk, due_date=date.today())

        assert signal_handler.call_count == 1

    def test_dont_mark_account_as_delinquent_when_account_balance_is_0(self):
        new_delinquent_account_ids, _ = (
            accounts.get_accounts_which_delinquent_status_has_to_change(
                [self.account.id]
            )
        )
        assert not new_delinquent_account_ids

    def test_mark_account_as_delinquent_when_pending_invoices_greater_than_0(self):
        Charge.objects.create(
            account=self.account,
            amount=Money(10, 'CHF'),
            product_code='10CHF'
        )
        accounts.create_invoices(account_id=self.account.pk, due_date=date.today())
        new_delinquent_account_ids, _ = (
            accounts.get_accounts_which_delinquent_status_has_to_change(
                [self.account.id]
            )
        )
        assert self.account.id in new_delinquent_account_ids

    def test_dont_mark_account_as_delinquent_when_account_has_a_positive_balance(self):
        Charge.objects.create(
            account=self.account,
            amount=Money(10, 'CHF'),
            product_code='10CHF'
        )
        invoice = accounts.create_invoices(
            account_id=self.account.pk,
            due_date=date.today()
        )[0]
        invoice.status = Invoice.PAID
        invoice.save()
        new_delinquent_account_ids, _ = (
            accounts.get_accounts_which_delinquent_status_has_to_change(
                [self.account.id]
            )
        )
        assert not new_delinquent_account_ids

    def test_toggle_delinquent_status(self):
        self.account.delinquent = False
        self.account.save()
        accounts.toggle_delinquent_status([self.account.pk])
        self.account.refresh_from_db()
        assert self.account.delinquent

    def test_update_account_from_delinquent_to_compliant(self):
        self.account.delinquent = True
        self.account.save()
        _, compliant_account_ids = (
            accounts.get_accounts_which_delinquent_status_has_to_change(
                [self.account.id]
            )
        )
        assert compliant_account_ids
