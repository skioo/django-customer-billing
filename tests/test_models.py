from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils.dateparse import parse_datetime
from moneyed import Money

from billing.models import Account, Charge, CreditCard, Invoice, Transaction
from billing.total import Total


class InvoiceTest(TestCase):
    def test_it_should_compute_the_invoice_total(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        invoice = Invoice.objects.create(account=account)
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=account, invoice=invoice, amount=Money(-3, 'CHF'), description='a credit')

        with self.assertNumQueries(1):
            assert invoice.total() == Total(7, 'CHF')

    def test_it_should_compute_the_invoice_total_in_multiple_currencies(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        invoice = Invoice.objects.create(account=account)
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=account, invoice=invoice, amount=Money(-3, 'EUR'), description='a credit')

        with self.assertNumQueries(1):
            assert invoice.total() == Total(10, 'CHF', -3, 'EUR')


class CreditCardTest(TestCase):
    def test_expiry(self):
        credit_card = CreditCard.objects.create(
            account_id='11111111-1111-1111-1111-111111111111',
            type='VIS',
            number='1111',
            expiry_month=12,
            expiry_year=88,
            psp_uri='test:creditcardtoken/12345')
        assert credit_card.expiry_date == date(2088, 12, 31)
        assert not credit_card.is_expired()
        assert credit_card.is_expired(as_of=date(2089, 1, 1))


class AccountTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('a-username')

    def test_it_should_compute_the_account_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='a charge')
        Charge.objects.create(account=account, amount=Money(-3, 'CHF'), description='a credit')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=True,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_uri='test:payment/12345')
        with self.assertNumQueries(2):
            assert account.balance() == Total(-1, 'CHF')

    def test_unsuccessful_transactions_should_not_impact_the_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), description='a charge')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=False,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_uri='test:payment/12345')
        with self.assertNumQueries(2):
            assert account.balance() == Total(-10, 'CHF')

    def test_balance_as_of_date_should_ignore_more_recent_charges(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
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
