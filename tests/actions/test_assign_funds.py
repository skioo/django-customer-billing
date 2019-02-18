from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from moneyed import Money

from billing.actions import accounts
from billing.models import Account, Charge, Transaction, Invoice, CREDIT_REMAINING, CARRIED_FORWARD
from billing.total import Total
from ..helper import assert_attrs


class AssignFundsToInvoiceTest(TestCase):
    """ Test assigning funds to a single invoice.
    """

    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')

    def test_it_should_do_nothing_when_no_funds(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')

        with self.assertNumQueries(5):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert not paid

    def test_it_should_ignore_funds_that_are_assigned_to_an_invoice(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        Transaction.objects.create(account=self.account, amount=Money(100, 'CHF'), invoice_id=999, success=True)

        with self.assertNumQueries(5):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert not paid

    def test_it_should_ignore_unsuccesful_payment(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        Transaction.objects.create(account=self.account, amount=Money(100, 'CHF'), success=False)

        with self.assertNumQueries(5):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert not paid

    def test_it_should_assign_funds_even_if_not_enough_to_pay_invoice_fully(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        transaction = Transaction.objects.create(account=self.account, amount=Money(31, 'CHF'), success=True)

        with self.assertNumQueries(6):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert not paid
        transaction.refresh_from_db()
        assert transaction.invoice == invoice
        invoice.refresh_from_db()
        assert invoice.status == Invoice.PENDING
        assert invoice.due() == Total([Money(9, 'CHF')])

    def test_it_should_assign_payment_to_invoice_and_pay_it(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        transaction = Transaction.objects.create(account=self.account, amount=Money(40, 'CHF'), success=True)

        with self.assertNumQueries(7):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        transaction.refresh_from_db()
        assert transaction.invoice == invoice
        invoice.refresh_from_db()
        assert invoice.status == Invoice.PAID
        assert invoice.due() == Total([Money(0, 'CHF')])

    def test_it_should_assign_credit_to_invoice_and_pay_it(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        credit = Charge.objects.create(account=self.account, amount=Money(-40, 'CHF'))

        with self.assertNumQueries(7):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        credit.refresh_from_db()
        assert credit.invoice == invoice
        invoice.refresh_from_db()
        assert invoice.status == Invoice.PAID
        assert invoice.due() == Total([Money(0, 'CHF')])

    def test_it_should_assign_multiple_payments_to_invoice_and_pay_it(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        transaction_1 = Transaction.objects.create(account=self.account, amount=Money(15, 'CHF'), success=True)
        transaction_2 = Transaction.objects.create(account=self.account, amount=Money(25, 'CHF'), success=True)

        with self.assertNumQueries(8):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        transaction_1.refresh_from_db()
        assert transaction_1.invoice == invoice
        transaction_2.refresh_from_db()
        assert transaction_2.invoice == invoice
        invoice.refresh_from_db()
        assert invoice.status == Invoice.PAID
        assert invoice.due() == Total([Money(0, 'CHF')])

    def test_it_should_use_oldest_payments_first(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(11, 'CHF'), product_code='ACHARGE')
        transaction_1 = Transaction.objects.create(account=self.account, amount=Money(5, 'CHF'), success=True)
        transaction_2 = Transaction.objects.create(account=self.account, amount=Money(6, 'CHF'), success=True)
        transaction_3 = Transaction.objects.create(account=self.account, amount=Money(7, 'CHF'), success=True)

        with self.assertNumQueries(8):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        transaction_1.refresh_from_db()
        assert transaction_1.invoice == invoice
        transaction_2.refresh_from_db()
        assert transaction_2.invoice == invoice
        transaction_3.refresh_from_db()
        assert transaction_3.invoice is None

    def test_it_should_use_credits_before_payments(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(10, 'CHF'), product_code='ACHARGE')
        transaction = Transaction.objects.create(account=self.account, amount=Money(10, 'CHF'), success=True)
        credit = Charge.objects.create(account=self.account, amount=Money(-10, 'CHF'), product_code='ACREDIT')

        with self.assertNumQueries(7):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        # Verify that the credit was used (even though the transaction was older)
        transaction.refresh_from_db()
        assert transaction.invoice is None
        credit.refresh_from_db()
        assert credit.invoice == invoice

    def test_it_shoud_generate_credit_remaining_when_payment_is_larger_than_invoice(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        charge = Charge.objects.create(account=self.account, invoice=invoice,
                                       amount=Money(40, 'CHF'), product_code='ACHARGE')
        transaction = Transaction.objects.create(account=self.account, amount=Money(50, 'CHF'), success=True)

        with self.assertNumQueries(11):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        transaction.refresh_from_db()
        assert transaction.invoice == invoice
        invoice.refresh_from_db()
        assert_attrs(invoice,
                     {'status': Invoice.PAID,
                      'items': [
                          {'id': charge.id, 'amount': Money(40, 'CHF'), 'product_code': 'ACHARGE'},
                          {'amount': Money(10, 'CHF'), 'product_code': CARRIED_FORWARD}
                      ],
                      'transactions': [
                          {'id': transaction.id, 'amount': Money(50, 'CHF'), 'success': True}
                      ]})
        uninvoiced_charges = Charge.objects.uninvoiced(account_id=self.account.id)
        assert len(uninvoiced_charges) == 1
        uninvoiced_charge = uninvoiced_charges[0]
        assert_attrs(uninvoiced_charge,
                     {'amount': Money(-10, 'CHF'), 'product_code': CREDIT_REMAINING})

    def test_it_should_pay_invoice_with_already_assigned_payment(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Transaction.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), success=True)
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')

        with self.assertNumQueries(4):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert paid
        assert invoice.due() == Total([Money(0, 'CHF')])

    def test_it_should_ignore_funds_in_the_wrong_currency(self):
        invoice = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice, amount=Money(40, 'CHF'), product_code='ACHARGE')
        Transaction.objects.create(account=self.account, amount=Money(40, 'EUR'), success=True)
        Charge.objects.create(account=self.account, amount=Money(-40, 'EUR'))

        with self.assertNumQueries(5):
            paid = accounts.assign_funds_to_invoice(invoice_id=invoice.pk)
        assert not paid


class AssignFundsToAccountPendingInvoicesTest(TestCase):
    """ Test the chaining of assigning funds to multiple invoices in an account.
    """

    def setUp(self):
        user = User.objects.create_user('a-username')
        self.account = Account.objects.create(owner=user, currency='CHF')
        Transaction.objects.create(account=self.account, amount=Money(30, 'CHF'), success=True)
        self.invoice1 = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=self.invoice1, amount=Money(40, 'CHF'),
                              product_code='ACHARGE')

    def test_it_does_nothing_when_no_funds(self):
        paid_invoice_ids = accounts.assign_funds_to_account_pending_invoices(account_id=self.account.id)
        assert paid_invoice_ids == []

    def test_it_pays_invoices_in_different_currencies(self):
        invoice2 = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice2, amount=Money(5, 'EUR'),
                              product_code='BCHARGE')
        Transaction.objects.create(account=self.account, amount=Money(5, 'EUR'), success=True)
        Transaction.objects.create(account=self.account, amount=Money(10, 'CHF'), success=True)
        paid_invoice_ids = accounts.assign_funds_to_account_pending_invoices(account_id=self.account.id)
        assert paid_invoice_ids == [self.invoice1.pk, invoice2.pk]

        self.invoice1.refresh_from_db()
        assert_attrs(self.invoice1,
                     {'status': Invoice.PAID,
                      'items': [
                          {'amount': Money(40, 'CHF'), 'product_code': 'ACHARGE'},
                      ],
                      'transactions': [
                          {'amount': Money(30, 'CHF')},
                          {'amount': Money(10, 'CHF')},
                      ]})
        assert self.invoice1.due() == Total(Money(0, 'CHF'))

        invoice2.refresh_from_db()
        assert_attrs(invoice2,
                     {'status': Invoice.PAID,
                      'items': [
                          {'amount': Money(5, 'EUR'), 'product_code': 'BCHARGE'},
                      ],
                      'transactions': [
                          {'amount': Money(5, 'EUR')},
                      ]})
        assert invoice2.due() == Total(Money(0, 'EUR'))

    def test_full_scenario(self):
        # 1- At first the invoice is partially paid.
        paid_invoice_ids = accounts.assign_funds_to_account_pending_invoices(account_id=self.account.id)
        assert paid_invoice_ids == []
        self.invoice1.refresh_from_db()
        assert_attrs(self.invoice1,
                     {'status': Invoice.PENDING,
                      'items': [
                          {'amount': Money(40, 'CHF'), 'product_code': 'ACHARGE'},
                      ],
                      'transactions': [
                          {'amount': Money(30, 'CHF')},
                      ]})

        # 2- A payment is made with more than enough money to pay the invoice.
        transaction2 = Transaction.objects.create(account=self.account, amount=Money(28, 'CHF'), success=True)
        paid_invoice_ids = accounts.assign_funds_to_account_pending_invoices(account_id=self.account.id)
        assert paid_invoice_ids == [self.invoice1.pk]
        transaction2.refresh_from_db()
        assert transaction2.invoice == self.invoice1
        self.invoice1.refresh_from_db()
        assert_attrs(self.invoice1,
                     {'status': Invoice.PAID,
                      'items': [
                          {'amount': Money(40, 'CHF'), 'product_code': 'ACHARGE'},
                          {'amount': Money(18, 'CHF'), 'product_code': CARRIED_FORWARD},
                      ],
                      'transactions': [
                          {'amount': Money(30, 'CHF')},
                          {'amount': Money(28, 'CHF')},
                      ]})
        assert self.invoice1.due() == Total(Money(0, 'CHF'))
        uninvoiced_charges = Charge.objects.uninvoiced(account_id=self.account.id)
        assert len(uninvoiced_charges) == 1
        uninvoiced_charge = uninvoiced_charges[0]
        assert_attrs(uninvoiced_charge,
                     {'amount': Money(-18, 'CHF'), 'product_code': CREDIT_REMAINING})

        # 3- A second charge is added to the account.
        invoice2 = Invoice.objects.create(account_id=self.account.id, due_date=date.today())
        Charge.objects.create(account=self.account, invoice=invoice2, amount=Money(12, 'CHF'),
                              product_code='BCHARGE')
        paid_invoice_ids = accounts.assign_funds_to_account_pending_invoices(account_id=self.account.id)
        assert paid_invoice_ids == [invoice2.pk]
        invoice2.refresh_from_db()
        assert_attrs(invoice2,
                     {'status': Invoice.PAID,
                      'items': [
                          {'amount': Money(-18, 'CHF'), 'product_code': CREDIT_REMAINING},
                          {'amount': Money(12, 'CHF'), 'product_code': 'BCHARGE'},
                          {'amount': Money(6, 'CHF'), 'product_code': CARRIED_FORWARD},
                      ]})
        assert invoice2.due() == Total(Money(0, 'CHF'))
        uninvoiced_charges = Charge.objects.uninvoiced(account_id=self.account.id)
        assert len(uninvoiced_charges) == 1
        uninvoiced_charge = uninvoiced_charges[0]
        assert_attrs(uninvoiced_charge, {'amount': Money(-6, 'CHF'), 'product_code': CREDIT_REMAINING})
