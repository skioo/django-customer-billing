from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from moneyed import Money
from pytest import raises

from billing.models import Account, Charge, CreditCard, Invoice, Transaction, ProductProperty, CARRIED_FORWARD, \
    total_amount
from billing.total import Total
from .models import MyPSPCreditCard, MyPSPPayment


class InvoiceTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_payments_should_ignore_refunds(self):
        Transaction.objects.create(account=self.account, success=True, amount=Money(-10, 'CHF'))
        with self.assertNumQueries(1):
            qs = Transaction.successful.payments()
            assert not qs.exists()

    def test_in_currency(self):
        Transaction.objects.create(account=self.account, success=True, amount=Money(10, 'CHF'))
        Transaction.objects.create(account=self.account, success=True, amount=Money(20, 'EUR'))
        with self.assertNumQueries(1):
            result = list(Transaction.successful.in_currency('CHF'))
            assert len(result) == 1
            assert result[0].amount_currency == 'CHF'

    def test_uninvoiced_paymnents_should_return_uninvoiced_payment(self):
        Transaction.objects.create(account=self.account, success=True, amount=Money(10, 'CHF'))
        with self.assertNumQueries(1):
            qs = Transaction.successful.uninvoiced(account_id=self.account.pk).payments()
            assert qs.exists()

    def test_uninvoiced_payments_should_ignore_invoiced_transactions(self):
        Invoice.objects.create(id=1, account=self.account, due_date=date.today())
        Transaction.objects.create(account=self.account, success=True, invoice_id=1, amount=Money(10, 'CHF'))
        with self.assertNumQueries(1):
            qs = Transaction.successful.uninvoiced(account_id=self.account.pk).payments()
            assert not qs.exists()

    def test_it_should_determine_if_the_invoice_is_payable(self):
        invoice1 = Invoice.objects.create(account=self.account, status=Invoice.PENDING, due_date=date.today())
        with self.assertNumQueries(0):
            assert invoice1.in_payable_state
        invoice2 = Invoice.objects.create(account=self.account, status=Invoice.CANCELLED, due_date=date.today())
        with self.assertNumQueries(0):
            assert not invoice2.in_payable_state

    def test_it_should_select_payable_invoices(self):
        invoice_yesterday = Invoice.objects.create(account=self.account, status=Invoice.PENDING,
                                                   due_date=date.today() - timedelta(days=1))
        invoice_today = Invoice.objects.create(account=self.account, status=Invoice.PENDING, due_date=date.today())
        invoice_tomorrow = Invoice.objects.create(account=self.account, status=Invoice.PENDING,
                                                  due_date=date.today() + timedelta(days=1))
        Invoice.objects.create(account=self.account, status=Invoice.CANCELLED, due_date=date.today())
        Invoice.objects.create(account=self.account, status=Invoice.PAID, due_date=date.today())
        with self.assertNumQueries(1):
            payable_invoices = Invoice.objects.payable()
            assert set(payable_invoices) == {invoice_yesterday, invoice_today}
        with self.assertNumQueries(1):
            payable_invoices = Invoice.objects.payable(as_of=date.today() + timedelta(days=1))
            assert set(payable_invoices) == {invoice_yesterday, invoice_today, invoice_tomorrow}

    def test_it_should_compute_the_invoice_due(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-3, 'CHF'), product_code='ACREDIT')
        with self.assertNumQueries(2):
            assert invoice.due() == Total(7, 'CHF')

    def test_it_should_compute_the_invoice_due_ignoring_deleted_charges(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-3, 'CHF'), product_code='ACREDIT')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(1000, 'CHF'), product_code='ACHARGE',
                              deleted=True)
        with self.assertNumQueries(2):
            assert invoice.due() == Total(7, 'CHF')

    def test_it_should_compute_the_invoice_due_in_multiple_currencies(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-3, 'EUR'), product_code='ACREDIT')
        with self.assertNumQueries(2):
            assert invoice.due() == Total(10, 'CHF', -3, 'EUR')

    def test_it_should_compute_the_invoice_due_when_there_are_transactions(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Transaction.objects.create(account=self.account, invoice=invoice, amount=Money(8, 'CHF'), success=True)
        with self.assertNumQueries(2):
            assert invoice.due() == Total(2, 'CHF')

    def test_it_should_compute_the_invoice_due_when_overpayment(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Transaction.objects.create(account=self.account, invoice=invoice, amount=Money(15, 'CHF'), success=True)
        with self.assertNumQueries(2):
            assert invoice.due() == Total(-5, 'CHF')

    def test_total_charges_should_select_just_the_right_charges(self):
        invoice = Invoice.objects.create(account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(8, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(2, 'CHF'), product_code='BCHARGE')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(-1, 'CHF'), product_code='ACREDIT')
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(6, 'CHF'),
                              product_code=CARRIED_FORWARD)
        Transaction.objects.create(account=self.account, invoice=invoice, amount=Money(15, 'CHF'), success=True)
        with self.assertNumQueries(1):
            assert invoice.total_charges() == Total(10, 'CHF')
        # Just to demonstrate that the due amount is completely different:
        assert invoice.due() == Total(0, 'CHF')


class CreditCardTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_can_filter_valid_credit_cards(self):
        psp_credit_card1 = MyPSPCreditCard.objects.create(token='atoken1')
        CreditCard.objects.create(
            account=self.account,
            type='VIS',
            number='1111',
            expiry_month=1,
            expiry_year=17,
            psp_object=psp_credit_card1)

        psp_credit_card2 = MyPSPCreditCard.objects.create(token='atoken2')
        credit_card2 = CreditCard.objects.create(
            account=self.account,
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
            account=self.account,
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

    def test_it_should_return_only_open_accounts(self):
        Account.objects.create(owner=self.user, currency='CHF')
        user2 = User.objects.create_user('a-username-2')
        Account.objects.create(owner=user2, currency='EUR', status=Account.CLOSED)
        with self.assertNumQueries(1):
            open_accounts = Account.objects.open()
            assert len(open_accounts) == 1

    def test_it_should_filter_accounts_with_uninvoiced_positive_charges(self):
        account1 = Account.objects.create(owner=self.user, currency='CHF')
        invoice1 = Invoice.objects.create(account=account1, due_date=date.today())
        Charge.objects.create(account=account1, amount=Money(10, 'CHF'), product_code='ACHARGE',
                              invoice=invoice1)

        user2 = User.objects.create_user('a-username-2')
        account2 = Account.objects.create(owner=user2, currency='CHF')
        Charge.objects.create(account=account2, amount=Money(10, 'CHF'), product_code='ACHARGE')

        user3 = User.objects.create_user('a-username-3')
        account3 = Account.objects.create(owner=user3, currency='EUR')
        Charge.objects.create(account=account3, amount=Money(10, 'CHF'), product_code='ACHARGE', deleted=True)

        user4 = User.objects.create_user('a-username-4')
        account4 = Account.objects.create(owner=user4, currency='EUR')
        Charge.objects.create(account=account4, amount=Money(-10, 'CHF'), product_code='ACHARGE')

        with self.assertNumQueries(1):
            open_with_uninvoiced = Account.objects.with_uninvoiced_positive_charges()
            assert len(open_with_uninvoiced) == 1
            assert open_with_uninvoiced[0] == account2

    def test_uninvoiced_positive_charges_should_return_a_single_account_even_if_many_charges(self):
        account1 = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account1, amount=Money(1, 'CHF'), product_code='BCHARGE')
        Charge.objects.create(account=account1, amount=Money(10, 'CHF'), product_code='CCHARGE')

        with self.assertNumQueries(1):
            open_with_uninvoiced = Account.objects.with_uninvoiced_positive_charges()
            assert len(open_with_uninvoiced) == 1
            assert open_with_uninvoiced[0] == account1

    def test_should_filter_accounts_with_no_charges_since(self):
        account1 = Account.objects.create(owner=self.user, currency='CHF')
        old_charge_account1 = Charge.objects.create(account=account1, amount=Money(10, 'CHF'), product_code='ACHARGE')
        old_charge_account1.created = parse_datetime('2001-01-01T01:01:01Z')
        old_charge_account1.save()

        user2 = User.objects.create_user('a-username-2')
        account2 = Account.objects.create(owner=user2, currency='CHF')
        Charge.objects.create(account=account2, amount=Money(15, 'CHF'), product_code='BCHARGE')

        user3 = User.objects.create_user('a-username-3')
        account3 = Account.objects.create(owner=user3, currency='CHF')
        old_charge_account3 = Charge.objects.create(account=account3, amount=Money(10, 'CHF'), product_code='CCHARGE')
        old_charge_account3.created = parse_datetime('2001-01-01T01:01:01Z')
        old_charge_account3.save()
        Charge.objects.create(account=account3, amount=Money(15, 'CHF'), product_code='DCHARGE')

        with self.assertNumQueries(1):
            accounts = Account.objects.with_no_charges_since(parse_datetime('2017-01-01T01:01:01Z'))
            assert len(accounts) == 1
            assert accounts[0] == account1

    def test_no_charges_since_should_return_a_single_account_even_if_many_charges(self):
        account1 = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account1, amount=Money(10, 'CHF'), product_code='CCHARGE')
        Charge.objects.create(account=account1, amount=Money(10, 'CHF'), product_code='DCHARGE')

        with self.assertNumQueries(1):
            accounts = Account.objects.with_no_charges_since(timezone.now() + timedelta(days=1))
            assert len(accounts) == 1
            assert accounts[0] == account1

    def test_it_should_compute_the_account_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=account, amount=Money(-3, 'CHF'), product_code='ACREDIT')
        psp_payment = MyPSPPayment(payment_ref='apaymentref')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=True,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_object=psp_payment)
        with self.assertNumQueries(2):
            assert account.balance() == Total(-1, 'CHF')

    def test_unsuccessful_transactions_should_not_impact_the_balance(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        psp_payment = MyPSPPayment(payment_ref='apaymentref')
        Transaction.objects.create(account=account, amount=Money(6, 'CHF'), success=False,
                                   payment_method='VIS', credit_card_number='4111 1111 1111 1111',
                                   psp_object=psp_payment)
        with self.assertNumQueries(2):
            assert account.balance() == Total(-10, 'CHF')

    def test_balance_as_of_date_should_ignore_more_recent_charges(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        old_charge = Charge.objects.create(account=account, amount=Money(5, 'CHF'), product_code='OLD')
        # It's not possible to prevent auto-add-now from setting the current time, so we do 2 steps
        old_charge.created = parse_datetime('2015-01-01T00:00:00Z')
        old_charge.save()
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), product_code='TODAY')
        with self.assertNumQueries(2):
            assert account.balance(as_of=parse_datetime('2016-06-06T00:00:00Z')) == Total([Money(-5, 'CHF')])

    def test_it_should_compute_the_account_balance_in_multiple_currencies(self):
        account = Account.objects.create(owner=self.user, currency='CHF')
        Charge.objects.create(account=account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=account, amount=Money(-3, 'EUR'), product_code='ACREDIT')
        with self.assertNumQueries(2):
            assert account.balance() == Total(-10, 'CHF', 3, 'EUR')

    def test_it_should_select_accounts_with_pending_invoices(self):
        Account.objects.create(owner=self.user, currency='CHF')
        user2 = User.objects.create_user('user2')
        account2 = Account.objects.create(owner=user2, currency='CHF')
        Invoice.objects.create(account=account2, due_date=date.today())
        user3 = User.objects.create_user('user3')
        account3 = Account.objects.create(owner=user3, currency='CHF')
        Invoice.objects.create(account=account3, due_date=date.today(), status=Invoice.PAID)
        with self.assertNumQueries(1):
            accounts = list(Account.objects.with_pending_invoices().values_list('id', flat=True))
        assert accounts == [account2.id]


class ChargeTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_in_currency(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, deleted=True, amount=Money(5, 'EUR'), product_code='BCHARGE')
        with self.assertNumQueries(1):
            result = list(Charge.objects.in_currency(currency='CHF'))
            assert len(result) == 1
            assert result[0].amount_currency == 'CHF'

    def test_uninvoiced_should_ignore_invoiced_charges(self):
        Invoice.objects.create(id=1, account=self.account, due_date=date.today())
        Charge.objects.create(account=self.account, invoice_id=1, amount=Money(10, 'CHF'), product_code='ACHARGE')
        with self.assertNumQueries(2):
            uc = Charge.objects.uninvoiced(account_id=self.account.pk)
            assert len(uc) == 0
            assert total_amount(uc) == Total()

    def test_uninvoiced_should_consider_credits(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-30, 'CHF'), product_code='ACREDIT')
        with self.assertNumQueries(2):
            uc = Charge.objects.uninvoiced(account_id=self.account.pk)
            assert len(uc) == 2
            assert total_amount(uc) == Total(-20, 'CHF')

    def test_uninvoiced_can_be_in_multiple_currencies(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-30, 'EUR'), product_code='ACREDIT')
        with self.assertNumQueries(2):
            uc = Charge.objects.uninvoiced(account_id=self.account.pk)
            assert len(uc) == 2
            assert total_amount(uc) == Total(10, 'CHF', -30, 'EUR')

    def test_uninvoiced_should_ignore_deleted_charges(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, deleted=True, amount=Money(5, 'CHF'), product_code='BCHARGE')
        with self.assertNumQueries(2):
            uc = Charge.objects.uninvoiced(account_id=self.account.pk)
            assert len(uc) == 1
            assert total_amount(uc) == Total(10, 'CHF')

    def test_it_can_create_charge_with_both_ad_hoc_label_and_product_code(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'),
                                       product_code='ACHARGE', ad_hoc_label='hai')
        charge.full_clean()

    def test_it_must_have_ad_hoc_code_or_product_code(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'))
        with raises(ValidationError):
            charge.full_clean()

    def test_it_can_create_product_properties(self):
        charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        charge.product_properties.create(name='color', value='blue')
        charge.full_clean()
        # Now read back from the db
        retrieved = Charge.objects.all()[0]
        assert retrieved.product_properties.count() == 1
        assert retrieved.product_properties.all()[0].name == 'color'

    def test_it_can_mark_charge_as_deleted(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'),
                              product_code='ACHARGE', deleted=True)

    def test_it_can_reverse(self):
        the_charge = Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), product_code='REVERSAL',
                              reverses=the_charge)


class ProductPropertyTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        self.charge = Charge.objects.create(account=account, amount=Money(10, 'CHF'), product_code='ACHARGE')

    def test_it_can_set_product_properties(self):
        ProductProperty.objects.create(charge=self.charge, name='color', value='blue')
        ProductProperty.objects.create(charge=self.charge, name='size', value='10')

    def test_it_cannot_redefine_a_property(self):
        ProductProperty.objects.create(charge=self.charge, name='color', value='blue')
        with raises(IntegrityError):
            ProductProperty.objects.create(charge=self.charge, name='color', value='red')

    def test_it_cannot_use_an_empty_property_name(self):
        p = ProductProperty.objects.create(charge=self.charge, name='', value='red')
        with raises(ValidationError):
            p.full_clean()

    def test_name_should_start_with_a_letter(self):
        p = ProductProperty.objects.create(charge=self.charge, name='1', value='red')
        with raises(ValidationError):
            p.full_clean()

    def test_property_value_cannot_be_none(self):
        with raises(IntegrityError):
            ProductProperty.objects.create(charge=self.charge, name='color', value=None)

    def test_property_value_can_be_empty(self):
        p = ProductProperty.objects.create(charge=self.charge, name='remark', value='')
        p.full_clean()
