from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils.dateparse import parse_datetime
from moneyed import Money

from billing.models import Account, Charge, CreditCard, Invoice, Transaction
from billing.total import Total
from .models import MyPSPCreditCard, MyPSPPayment


class InvoiceTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_should_determine_if_the_invoice_is_payable(self):
        invoice1 = Invoice.objects.create(account=self.account, status=Invoice.PENDING)
        with self.assertNumQueries(0):
            assert invoice1.in_payable_state
        invoice2 = Invoice.objects.create(account=self.account, status=Invoice.CANCELLED)
        with self.assertNumQueries(0):
            assert not invoice2.in_payable_state

    def test_it_should_select_payable_invoices(self):
        invoice1 = Invoice.objects.create(account=self.account, status=Invoice.PENDING)
        invoice2 = Invoice.objects.create(account=self.account, status=Invoice.PAST_DUE)
        Invoice.objects.create(account=self.account, status=Invoice.CANCELLED)
        Invoice.objects.create(account=self.account, status=Invoice.PAYED)
        with self.assertNumQueries(1):
            payable_invoices = Invoice.objects.payable().order_by('status')
            assert len(payable_invoices) == 2
            assert payable_invoices[0] == invoice2
            assert payable_invoices[1] == invoice1

    def test_it_should_compute_the_invoice_total(self):
        invoice = Invoice.objects.create(account=self.account)
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-3, 'CHF'), description='a credit')
        with self.assertNumQueries(1):
            assert invoice.total() == Total(7, 'CHF')

    def test_it_should_compute_the_invoice_total_in_multiple_currencies(self):
        invoice = Invoice.objects.create(account=self.account)
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-3, 'EUR'), description='a credit')
        with self.assertNumQueries(1):
            assert invoice.total() == Total(10, 'CHF', -3, 'EUR')


class CreditCardTest(TestCase):
    def test_it_can_filter_valid_credit_cards(self):
        psp_credit_card1 = MyPSPCreditCard.objects.create(token='atoken1')
        CreditCard.objects.create(
            account_id='11111111-1111-1111-1111-111111111111',
            type='VIS',
            number='1111',
            expiry_month=1,
            expiry_year=17,
            psp_object=psp_credit_card1)

        psp_credit_card2 = MyPSPCreditCard.objects.create(token='atoken2')
        credit_card2 = CreditCard.objects.create(
            account_id='22222222-2222-2222-2222-222222222222',
            type='VIS',
            number='2222',
            expiry_month=1,
            expiry_year=30,
            psp_object=psp_credit_card2)

        with self.assertNumQueries(1):
            valid_credit_cards = CreditCard.objects.valid()
            assert len(valid_credit_cards) == 1
            assert valid_credit_cards[0] == credit_card2

    def test_it_can_determine_if_a_credit_card_is_valid(self):
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        credit_card = CreditCard.objects.create(
            account_id='11111111-1111-1111-1111-111111111111',
            type='VIS',
            number='1111',
            expiry_month=12,
            expiry_year=30,
            psp_object=psp_credit_card)
        assert credit_card.expiry_date == date(2030, 12, 31)
        assert credit_card.is_valid()
        assert not credit_card.is_valid(as_of=date(2031, 1, 1))


class AccountTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('a-username')

    def test_it_should_return_open_accounts(self):
        Account.objects.create(owner=self.user, currency='CHF')
        user2 = User.objects.create_user('a-username-2')
        Account.objects.create(owner=user2, currency='EUR', status=Account.CLOSED)
        with self.assertNumQueries(1):
            open_accounts = Account.open.all()
            assert len(open_accounts) == 1

    def test_it_should_filter_accounts_with_uninvoiced_charges(self):
        account1 = Account.objects.create(owner=self.user, currency='CHF')
        invoice1 = Invoice.objects.create(account=account1)
        Charge.objects.create(account=account1, amount=Money(10, 'CHF'), description='a charge',
                              invoice=invoice1)

        user2 = User.objects.create_user('a-username-2')
        account2 = Account.objects.create(owner=user2, currency='EUR', status=Account.CLOSED)
        Charge.objects.create(account=account2, amount=Money(10, 'CHF'), description='a charge')

        user3 = User.objects.create_user('a-username-3')
        account3 = Account.objects.create(owner=user3, currency='EUR')
        Charge.objects.create(account=account3, amount=Money(10, 'CHF'), description='a charge')

        user4 = User.objects.create_user('a-username-4')
        Account.objects.create(owner=user4, currency='EUR')

        with self.assertNumQueries(1):
            open_with_uninvoiced = Account.open.with_uninvoiced_charges()
            assert len(open_with_uninvoiced) == 1
        assert open_with_uninvoiced[0] == account3

    def test_it_should_compute_the_account_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=account, amount=Money(-3, 'CHF'), description='a credit')
        psp_payment = MyPSPPayment(payment_ref='apaymentref')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=True,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_object=psp_payment)
        with self.assertNumQueries(2):
            assert account.balance() == Total(-1, 'CHF')

    def test_unsuccessful_transactions_should_not_impact_the_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='a charge')
        psp_payment = MyPSPPayment(payment_ref='apaymentref')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=False,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_object=psp_payment)
        with self.assertNumQueries(2):
            assert account.balance() == Total(-10, 'CHF')

    def test_balance_as_of_date_should_ignore_more_recent_charges(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        # It's not possible to prevent auto-add-now from setting the current time, so we do 2 steps
        old_charge = Charge.objects.create(account=account, amount=Money(5, 'CHF'), description='old charge')
        old_charge.created = parse_datetime('2015-01-01T00:00:00Z')
        old_charge.save()
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='today charge')
        with self.assertNumQueries(2):
            assert account.balance(as_of=parse_datetime('2016-06-06T00:00:00Z')) == Total([Money(-5, 'CHF')])

    def test_it_should_compute_the_account_balance_in_multiple_currencies(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=account, amount=Money(-3, 'EUR'), description='a credit')
        with self.assertNumQueries(2):
            assert account.balance() == Total(-10, 'CHF', 3, 'EUR')


class ChargeTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_uninvoiced_charges_should_ignore_invoiced_charges(self):
        Charge.objects.create(account=self.account, invoice_id=1, amount=Money(10, 'CHF'), description='a charge')
        with self.assertNumQueries(2):
            uc, total = Charge.objects.uninvoiced_with_total(account_id=self.account.pk)
            assert uc == []
            assert total == Total()

    def test_uninvoiced_charges_should_consider_credits(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, amount=Money(-30, 'CHF'), description='a credit')
        with self.assertNumQueries(2):
            uc, total = Charge.objects.uninvoiced_with_total(account_id=self.account.pk)
            assert len(uc) == 2
            assert total == Total(-20, 'CHF')

    def test_uninvoiced_charges_can_be_in_multiple_currencies(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=self.account, amount=Money(-30, 'EUR'), description='a credit')
        with self.assertNumQueries(2):
            uc, total = Charge.objects.uninvoiced_with_total(account_id=self.account.pk)
            assert len(uc) == 2
            assert total == Total(10, 'CHF', -30, 'EUR')
