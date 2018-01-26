from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from moneyed import Money
from pytest import raises

from billing.actions import accounts, invoices, credit_cards, charges
from billing.models import Account, Charge, CreditCard, Invoice
from billing.psp import register, unregister
from billing.total import Total
from .models import MyPSPCreditCard
from .my_psp import MyPSP


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
        assert not accounts.create_invoices(account_id=self.account.pk)

    def test_it_should_not_create_an_invoice_when_no_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), product_code='ACREDIT')
        assert not accounts.create_invoices(account_id=self.account.pk)

    def test_it_should_create_an_invoice_when_money_is_due(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='ACHARGE')
        Charge.objects.create(account=self.account, amount=Money(-3, 'CHF'), product_code='ACREDIT')
        invoices = accounts.create_invoices(account_id=self.account.pk)
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.total() == Total(7, 'CHF')
        assert invoice.items.count() == 2

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoices(account_id=self.account.pk)

    def test_it_should_handle_multicurrency_univoiced_charges(self):
        Charge.objects.create(account=self.account, amount=Money(10, 'CHF'), product_code='10CHF')
        Charge.objects.create(account=self.account, amount=Money(30, 'EUR'), product_code='30EURO')
        invoices = accounts.create_invoices(account_id=self.account.pk)
        assert len(invoices) == 2

        # For some reason the output is always sorted. This makes asserting easy
        invoice1 = invoices[0]
        items1 = invoice1.items.all()
        assert len(items1) == 1
        assert items1[0].product_code == '10CHF'
        assert invoice1.total().currencies() == ['CHF']

        invoice2 = invoices[1]
        items2 = invoice2.items.all()
        assert len(items2) == 1
        assert items2[0].product_code == '30EURO'
        assert invoice2.total().currencies() == ['EUR']

        # Verify there is nothing left to invoice on this account
        assert not accounts.create_invoices(account_id=self.account.pk)


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
        invoice = Invoice.objects.create(account=account)

        with raises(invoices.PreconditionError, match='Cannot pay empty invoice\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_prevent_paying_an_already_paid_invoice(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        invoice = Invoice.objects.create(account=account, status=Invoice.PAID)

        with raises(invoices.PreconditionError, match='Cannot pay invoice with status PAID\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_not_attempt_payment_when_no_valid_credit_card(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=11,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account)
        Charge.objects.create(account=account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')

        with raises(invoices.PreconditionError, match='No valid credit card on account\.'):
            invoices.pay_with_account_credit_cards(invoice.pk)

    def test_it_should_pay_when_all_is_right(self):
        user = User.objects.create_user('a-username')
        account = Account.objects.create(owner=user, currency='CHF')
        psp_credit_card = MyPSPCreditCard.objects.create(token='atoken')
        CreditCard.objects.create(account=account, type='VIS',
                                  number='1111', expiry_month=12, expiry_year=30,
                                  psp_object=psp_credit_card)
        invoice = Invoice.objects.create(account=account)
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
        invoice = Invoice.objects.create(account=self.account)
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
