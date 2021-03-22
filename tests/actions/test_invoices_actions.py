from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import invoices
from billing.models import Account, Charge, CreditCard, Invoice
from billing.psp import register, unregister
from ..models import MyPSPCreditCard
from ..my_psp import MyPSP


class InvoicesActionsTest(TestCase):
    def setUp(self):
        self.psp = MyPSP()
        register(self.psp)

    def tearDown(self):
        unregister(self.psp)

    def test_it_should_prevent_paying_an_empty_invoice(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account, due_date=date.today())

        with raises(invoices.PreconditionError, match='Cannot pay empty invoice\\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_prevent_paying_an_already_paid_invoice(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        invoice = Invoice.objects.create(account=account, due_date=date.today(), status=Invoice.PAID)

        with raises(invoices.PreconditionError, match='Cannot pay invoice with status PAID\\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_not_attempt_payment_when_no_valid_credit_card(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=11,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account, due_date=date.today())
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')

        with raises(invoices.PreconditionError, match='No valid credit card on account\\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_not_attempt_payment_when_closed_account(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF', status=Account.CLOSED)
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account, due_date=date.today())
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')

        with raises(invoices.PreconditionError, match=f'Cannot pay invoice with closed account {account}.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_pay_when_all_is_right(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account, due_date=date.today())
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')

        payment = invoices.pay_with_account_credit_cards(invoice.pk)
        assert payment
        assert payment.success

        invoice.refresh_from_db()
        assert invoice.status == Invoice.PAID
        assert invoice.transactions.count() == 1
        assert invoice.transactions.first() == payment

        account.refresh_from_db()
        assert account.transactions.count() == 1
        assert account.transactions.first() == payment

    def test_it_should_use_active_credit_cards_before_inactive(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card_1111 = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card_1111, status=CreditCard.INACTIVE)
        psp_credit_card_2222 = MyPSPCreditCard.objects.create(token='btoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='2222', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card_2222)

        invoice = Invoice.objects.create(account=account, due_date=date.today())
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')

        payment = invoices.pay_with_account_credit_cards(invoice.pk)
        assert payment
        assert payment.success
        assert payment.credit_card_number == '2222'
