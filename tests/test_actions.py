from django.contrib.auth.models import User
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import invoices
from billing.models import Account, Charge, CreditCard, Invoice
from billing.psp import register, unregister
from .psp import MyPSP


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
