from django.contrib.auth.models import User
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import accounts, invoices
from billing.models import Account, Charge, CreditCard, Invoice
from billing.psp import register, unregister
from billing.total import Total
from .my_psp import MyPSP


class AccountActionsTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_should_not_create_invoice_when_money_is_owed_to_the_user(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, amount=Money(-30, 'CHF'), description='a credit')
        assert not accounts.create_invoice_if_pending_charges(account_id=self.account.pk)

    def test_it_should_not_create_an_invoice_when_no_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), description='a credit')
        assert not accounts.create_invoice_if_pending_charges(account_id=self.account.pk)

    def test_it_should_create_an_invoice_when_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, amount=Money(-3, 'CHF'), description='a credit')
        invoices = accounts.create_invoice_if_pending_charges(account_id=self.account.pk)
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.total() == Total(7, 'CHF')
        assert invoice.items.count() == 2

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoice_if_pending_charges(account_id=self.account.pk)

    def test_it_should_handle_multicurrency_univoiced_charges(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a 10 CHF charge')
        Charge.objects.create(account=self.account, amount=Money(30, 'EUR'), description='a 30 EURO charge')
        invoices = accounts.create_invoice_if_pending_charges(account_id=self.account.pk)
        assert len(invoices) == 2

        # For some reason the output is always sorted. This makes asserting easy
        invoice1 = invoices[0]
        items1 = invoice1.items.all()
        assert len(items1) == 1
        assert items1[0].description == 'a 10 CHF charge'
        assert invoice1.items.count() == 1
        assert invoice1.total().currencies() == ['CHF']

        invoice2 = invoices[1]
        items2 = invoice2.items.all()
        assert len(items2) == 1
        assert items2[0].description == 'a 30 EURO charge'
        assert invoice2.total().currencies() == ['EUR']

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoice_if_pending_charges(account_id=self.account.pk)


class InvoicesActionsTest(TestCase):
    def setUp(self):
        register('test', MyPSP())

    def tearDown(self):
        unregister('test')

    def test_it_should_prevent_paying_an_empty_invoice(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=18,
                                  psp_uri='test:token/12345')
        invoice = Invoice.objects.create(account=account)

        with raises(invoices.PreconditionError, match='Cannot pay empty invoice.'):
            invoices.pay(invoice.pk)

    def test_it_should_pay_when_all_is_right(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=18,
                                  psp_uri='test:token/12345')
        invoice = Invoice.objects.create(account=account)
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), description='a charge')

        payment = invoices.pay(invoice.pk)
        assert payment.success

        invoice.refresh_from_db()
        assert invoice.status == Invoice.PAYED
        assert invoice.transactions.count() == 1
        assert invoice.transactions.first() == payment

        account.refresh_from_db()
        assert account.transactions.count() == 1
        assert account.transactions.first() == payment
