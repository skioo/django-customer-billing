import calendar
from datetime import date, datetime
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Model, PROTECT, Sum
from django.utils.translation import ugettext_lazy as _
from django_fsm import FSMField, transition
from djmoney.models.fields import CurrencyField, MoneyField
from moneyed import Money

from .psp import psp_uri_validator
from .total import Total


class OnlyOpenAccountsManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(status=Account.OPEN)


def total_amount(qs):
    aggregate = qs.values('amount_currency').annotate(sum=Sum('amount'))
    return Total(Money(amount=r['sum'], currency=r['amount_currency']) for r in aggregate)


class Account(Model):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    STATUS_CHOICES = (
        (OPEN, _('Open')),
        (CLOSED, _('Closed')),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='billing_account', on_delete=PROTECT)
    currency = CurrencyField(db_index=True)
    status = FSMField(max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True)

    objects = models.Manager()
    open = OnlyOpenAccountsManager()

    def balance(self, as_of: date = None):
        charges = Charge.objects.filter(account=self)
        transactions = Transaction.successful.filter(account=self)
        if as_of is not None:
            charges = charges.filter(created__lte=as_of)
            transactions = transactions.filter(created__lte=as_of)
        return total_amount(transactions) - total_amount(charges)

    @transition(field=status, source=OPEN, target=CLOSED)
    def close(self):
        pass

    @transition(field=status, source=CLOSED, target=OPEN)
    def reopen(self):
        pass

    def has_past_due_invoices(self):
        return Invoice.objects.filter(account=self, status=Invoice.PAST_DUE).exists()

    def __str__(self):
        return str(self.owner)


class Invoice(Model):
    PENDING = 'PENDING'
    PAST_DUE = 'PAST_DUE'
    PAYED = 'PAYED'
    CANCELLED = 'CANCELLED'
    STATUS_CHOICES = (
        (PENDING, _('Pending')),
        (PAST_DUE, _('Past-due')),
        (PAYED, _('Payed')),
        (CANCELLED, _('Cancelled')),
    )
    account = models.ForeignKey(Account, related_name='invoices', on_delete=PROTECT)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    status = FSMField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)

    @transition(field=status, source=PENDING, target=PAST_DUE)
    def mark_past_due(self):
        pass

    @transition(field=status, source=[PENDING, PAST_DUE], target=PAYED)
    def pay(self):
        pass

    @transition(field=status, source=PENDING, target=CANCELLED)
    def cancel(self):
        pass

    def total(self):
        return total_amount(Charge.objects.filter(invoice=self))

    def __str__(self):
        return '#{}'.format(self.id)


class Charge(Model):
    """
    A charge has a signed amount. If the amount is negative then the charge is in fact a credit.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    account = models.ForeignKey(Account, on_delete=PROTECT, related_name='charges')
    invoice = models.ForeignKey(Invoice, null=True, blank=True, related_name='items', on_delete=PROTECT)
    amount = MoneyField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)

    @property
    def type(self):
        a = self.amount.amount
        if a >= 0:
            return _('Charge')
        else:
            return _('Credit')

    @property
    def is_invoiced(self):
        return self.invoice is not None


########################################################################################################


class OnlySuccessfulTransactionsManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(success=True)


class Transaction(Model):
    """
    A transaction has a signed amount. If the amount is positive then it's a payment,
    otherwise it's a refund.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    account = models.ForeignKey(Account, related_name='transactions', on_delete=PROTECT)
    success = models.BooleanField()
    invoice = models.ForeignKey(Invoice, related_name='transactions', null=True, blank=True, on_delete=PROTECT)
    amount = MoneyField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(db_index=True, max_length=3)
    credit_card_number = models.CharField(max_length=255, blank=True)

    psp_uri = models.CharField(max_length=255, validators=[psp_uri_validator])

    objects = models.Manager()
    successful = OnlySuccessfulTransactionsManager()

    @property
    def type(self):
        a = self.amount.amount
        if a > 0:
            return _('Payment')
        elif a < 0:
            return _('Refund')

    def __str__(self):
        return '{}-{} ({})'.format(
            self.type,
            self.credit_card_number,
            'success' if self.success else 'failure')


def compute_expiry_date(two_digit_year: int, month: int) -> date:
    year = 2000 + two_digit_year
    _, last_day_of_month = calendar.monthrange(year, month)
    return date(year=year, month=month, day=last_day_of_month)


class CreditCard(Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    account = models.ForeignKey(Account, related_name='credit_cards', on_delete=PROTECT)
    type = models.CharField(db_index=True, max_length=3)
    number = models.CharField(max_length=255)
    expiry_month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    expiry_year = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(99)])
    expiry_date = models.DateField()  # A field in the database so we can search for expired cards

    psp_uri = models.CharField(max_length=255, validators=[psp_uri_validator])

    def is_expired(self, as_of: date = None):
        if as_of is None:
            as_of = datetime.now().date()
        return self.expiry_date < as_of

    def save(self, *args, **kwargs):
        if self.expiry_year is not None and self.expiry_month is not None:
            self.expiry_date = compute_expiry_date(two_digit_year=self.expiry_year, month=self.expiry_month)
        super().save(*args, **kwargs)
