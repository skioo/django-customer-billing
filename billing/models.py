import calendar
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import DefaultDict, Dict
from uuid import UUID

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import CASCADE, Model, PROTECT, QuerySet, SET_NULL, Sum
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, can_proceed, transition
from djmoney.models.fields import CurrencyField, MoneyField
from moneyed import Money

from .total import Total


def total_amount(qs) -> Total:
    """Sums the amounts of the objects in the queryset, keeping each currency separate.
    :param qs: A querystring containing objects that have an amount field of type Money.
    :return: A Total object.
    """
    aggregate = qs.values('amount_currency').annotate(sum=Sum('amount'))
    return Total(Money(amount=r['sum'], currency=r['amount_currency']) for r in aggregate)


########################################################################################################
# Accounts

class AccountQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status=Account.OPEN)

    def with_uninvoiced_positive_charges(self):
        return self.filter(
            charges__deleted=False,
            charges__amount__gt=0,
            charges__invoice__isnull=True
        ).distinct()

    def with_no_charges_since(self, dt: datetime):
        return self.exclude(charges__created__gte=dt)

    def with_pending_invoices(self):
        return self.filter(invoices__status=Invoice.PENDING).distinct()

    def solvent(self, currency_threshold_price_map: Dict[str, Decimal]):
        from .actions.accounts import (
            get_account_balance_map,
            get_account_valid_credit_card_map
        )
        account_valid_cc_map = get_account_valid_credit_card_map(self)
        account_balance_map = get_account_balance_map(self)
        solvent_billing_account_ids = [
            billing_account.id
            for billing_account in self
            if billing_account.is_solvent(
                currency_threshold_price_map,
                account_valid_cc_map,
                account_balance_map
            )
        ]
        return self.filter(id__in=solvent_billing_account_ids)

    def insolvent(self, currency_threshold_price_map: Dict[str, Decimal]):
        solvent_billing_accounts = self.solvent(currency_threshold_price_map)
        return self.exclude(id__in=solvent_billing_accounts.values('id'))


class Account(Model):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    STATUS_CHOICES = (
        (OPEN, _('Open')),
        (CLOSED, _('Closed')),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='billing_account', on_delete=PROTECT)
    currency = CurrencyField(db_index=True)
    status = FSMField(max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    delinquent = models.BooleanField(default=False, db_index=True)

    objects = AccountQuerySet.as_manager()

    def __str__(self):
        return str(self.owner)

    @transition(field=status, source=OPEN, target=CLOSED)
    def close(self):
        pass

    @transition(field=status, source=CLOSED, target=OPEN)
    def reopen(self):
        pass

    def balance(self, as_of: date = None):
        charges = Charge.objects.filter(account=self)
        transactions = Transaction.successful.filter(account=self)
        if as_of is not None:
            charges = charges.filter(created__lte=as_of)
            transactions = transactions.filter(created__lte=as_of)
        return total_amount(transactions) - total_amount(charges)

    def is_solvent(
        self,
        currency_threshold_price_map: Dict[str, Decimal],
        account_valid_cc_map: Dict[UUID, bool] = None,
        account_balance_map: DefaultDict[UUID, DefaultDict[str, Decimal]] = None
    ):
        """
        Given a map of currency thresholds determines if the account is solvent

        An account is solvent when:
            * Has a valid and active credit card to pay OR
            * Has enough balance to pay

        In currency_threshold_price_map param you have to specify the amount threshold
        for each currency. If the account has enough of one of the currencies then
        is solvent. Ex:
        currency_threshold_price_map {
            'CHF': Decimal(10.83),
            'EUR': Decimal(10.),
            'NOK': Decimal(103.97)
        }

        Note: account_valid_cc_map and account_balance_map can be passed from outside
              in order to improve the efficiency when we require to know if several
              accounts are solvent
        """
        if not account_valid_cc_map:
            from .actions.accounts import get_account_valid_credit_card_map
            account_valid_cc_map = get_account_valid_credit_card_map(
                Account.objects.filter(id=self.id)
            )

        if not account_balance_map:
            from .actions.accounts import get_account_balance_map
            accounts = Account.objects.filter(id=self.id)
            account_balance_map = get_account_balance_map(accounts)

        return (
            account_valid_cc_map[self.id] or
            self.has_enough_balance(account_balance_map, currency_threshold_price_map)
        )

    def has_enough_balance(
        self,
        account_balance_map: DefaultDict[UUID, DefaultDict[str, Decimal]],
        currency_threshold_price_map: Dict[str, Decimal]
    ) -> bool:
        for currency, balance in account_balance_map[self.id].items():
            if balance >= currency_threshold_price_map[currency]:
                return True
        return False

    def has_usable_credit_cards(self) -> bool:
        credit_cards = CreditCard.objects.filter(
            account=self,
            status=CreditCard.ACTIVE
        ).valid()
        return credit_cards.exists()


########################################################################################################
# Invoices

class InvoiceQuerySet(models.QuerySet):
    def payable(self, as_of: date = None) -> QuerySet:
        if as_of is None:
            as_of = date.today()
        return self.filter(status=Invoice.PENDING, due_date__lte=as_of)


class Invoice(Model):
    PENDING = 'PENDING'
    PAID = 'PAID'
    CANCELLED = 'CANCELLED'
    STATUS_CHOICES = (
        (PENDING, _('Pending')),
        (PAID, _('Paid')),
        (CANCELLED, _('Cancelled')),
    )
    account = models.ForeignKey(Account, related_name='invoices', on_delete=PROTECT)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    due_date = models.DateField()
    status = FSMField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)

    objects = InvoiceQuerySet.as_manager()

    @transition(field=status, source=[PENDING], target=PAID)
    def pay(self):
        pass

    @transition(field=status, source=[PENDING], target=CANCELLED)
    def cancel(self):
        pass

    @property
    def in_payable_state(self):
        return can_proceed(self.pay)

    def total_charges(self):
        """
        Represents the 'goods' acquired in the invoice.
        """
        selected_charges = Charge.objects \
            .filter(invoice=self) \
            .charges() \
            .exclude(product_code=CARRIED_FORWARD)
        return total_amount(selected_charges)

    def due(self):
        """
        The amount due for this invoice. Takes into account all entities in the invoice.
        Can be < 0 if the invoice was overpaid.
        """
        invoice_charges = Charge.objects.filter(invoice=self)
        invoice_transactions = Transaction.successful.filter(invoice=self)
        return total_amount(invoice_charges) - total_amount(invoice_transactions)

    def __str__(self):
        return '#{}'.format(self.id)


########################################################################################################
# Charges

product_code_validator = RegexValidator(regex=r'^[A-Z0-9]{4,10}$',
                                        message='Between 4 and 10 uppercase letters or digits')


class ChargeQuerySet(models.QuerySet):
    def uninvoiced(self, account_id: str) -> QuerySet:
        return self.filter(invoice=None, account_id=account_id)

    def charges(self) -> QuerySet:
        return self.filter(amount__gt=0)

    def credits(self) -> QuerySet:
        return self.filter(amount__lt=0)

    def in_currency(self, currency: str) -> QuerySet:
        return self.filter(amount_currency=currency)


class ChargeManager(models.Manager):

    def get_queryset(self):
        return ChargeQuerySet(self.model, using=self._db).exclude(deleted=True)

    def uninvoiced(self, account_id: str) -> QuerySet:
        return self.get_queryset().uninvoiced(account_id)

    def charges(self) -> QuerySet:
        return self.get_queryset().charges()

    def credits(self) -> QuerySet:
        return self.get_queryset().credits()

    def in_currency(self, currency: str) -> QuerySet:
        return self.get_queryset().in_currency(currency)


class Charge(Model):
    """
    A charge has a signed amount. If the amount is negative then the charge is in fact a credit.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    account = models.ForeignKey(Account, on_delete=PROTECT, related_name='charges')
    invoice = models.ForeignKey(Invoice, null=True, blank=True, related_name='items', on_delete=SET_NULL)
    amount = MoneyField(max_digits=12, decimal_places=2)
    ad_hoc_label = models.TextField(blank=True, help_text='When not empty, this is shown verbatim to the user.')
    product_code = models.CharField(max_length=20, blank=True, validators=[product_code_validator], db_index=True,
                                    help_text='Identifies the kind of product being charged or credited')
    reverses = models.OneToOneField('self', null=True, blank=True, related_name='reversed_by', on_delete=PROTECT)
    deleted = models.BooleanField(default=False, db_index=True)

    objects = ChargeManager()

    all_charges = models.Manager()  # Includes deleted charges

    def clean(self):
        if not (self.ad_hoc_label or self.product_code):
            raise ValidationError('Either the ad-hoc-label or the product-code must be filled.')

    @property
    def type(self):
        a = self.amount.amount
        if a >= 0:
            return _('Charge')
        else:
            return _('Credit')


product_property_name_validator = RegexValidator(regex=r'^[a-z]\w*$',
                                                 flags=re.ASCII | re.IGNORECASE,
                                                 message='a letter maybe followed by letters, numbers, or underscores')


class ProductProperty(Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    charge = models.ForeignKey(Charge, on_delete=CASCADE, related_name='product_properties')
    name = models.CharField(max_length=100, validators=[product_property_name_validator])
    value = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ['charge', 'name']


########################################################################################################
# Transactions

CARRIED_FORWARD = 'CARRIED_FORWARD'
CREDIT_REMAINING = 'CREDIT_REMAINING'


class TransactionQuerySet(models.QuerySet):
    def uninvoiced(self, account_id: str) -> QuerySet:
        return self.filter(invoice=None, account_id=account_id)

    def payments(self) -> QuerySet:
        return self.filter(amount__gt=0)

    def refunds(self) -> QuerySet:
        return self.filter(amount__lt=0)

    def in_currency(self, currency: str) -> QuerySet:
        return self.filter(amount_currency=currency)


class OnlySuccessfulTransactionsManager(models.Manager):
    def get_queryset(self):
        return TransactionQuerySet(self.model, using=self._db).filter(success=True)

    def uninvoiced(self, account_id: str) -> QuerySet:
        return self.get_queryset().uninvoiced(account_id)

    def payments(self) -> QuerySet:
        return self.get_queryset().payments()

    def refunds(self) -> QuerySet:
        return self.get_queryset().refunds()

    def in_currency(self, currency: str) -> QuerySet:
        return self.get_queryset().in_currency(currency)


class Transaction(Model):
    """
    A transaction has a signed amount. If the amount is positive then it's a payment,
    otherwise it's a refund.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    account = models.ForeignKey(Account, related_name='transactions', on_delete=PROTECT)
    success = models.BooleanField()
    invoice = models.ForeignKey(Invoice, related_name='transactions', null=True, blank=True, on_delete=PROTECT)
    amount = MoneyField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(db_index=True, max_length=3)
    credit_card_number = models.CharField(max_length=255, blank=True)

    psp_content_type = models.ForeignKey(ContentType, blank=True, null=True, on_delete=CASCADE)
    psp_object_id = models.UUIDField(blank=True, null=True, db_index=True)
    psp_object = GenericForeignKey('psp_content_type', 'psp_object_id')

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


########################################################################################################
# Credit Cards

def compute_expiry_date(two_digit_year: int, month: int) -> date:
    year = 2000 + two_digit_year
    _, last_day_of_month = calendar.monthrange(year, month)
    return date(year=year, month=month, day=last_day_of_month)


class CreditCardQuerySet(models.QuerySet):
    def valid(self, as_of: date = None):
        if as_of is None:
            as_of = date.today()
        return self.filter(expiry_date__gte=as_of)


class CreditCard(Model):
    ACTIVE = 'ACTIVE'
    INACTIVE = 'INACTIVE'
    STATUS_CHOICES = (
        (ACTIVE, _('Active')),
        (INACTIVE, _('Inactive')),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    account = models.ForeignKey(Account, related_name='credit_cards', on_delete=PROTECT)
    type = models.CharField(db_index=True, max_length=3)
    number = models.CharField(max_length=255)
    expiry_month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    expiry_year = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(99)])
    expiry_date = models.DateField()  # A field in the database so we can search for expired cards

    psp_content_type = models.ForeignKey(ContentType, on_delete=CASCADE)
    psp_object_id = models.UUIDField(db_index=True)
    psp_object = GenericForeignKey('psp_content_type', 'psp_object_id')

    status = FSMField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE, db_index=True)

    objects = CreditCardQuerySet.as_manager()

    @transition(field=status, source=ACTIVE, target=INACTIVE)
    def deactivate(self):
        pass

    @transition(field=status, source=INACTIVE, target=ACTIVE)
    def reactivate(self):
        pass

    def is_valid(self, as_of: date = None):
        if as_of is None:
            as_of = datetime.now().date()
        return self.expiry_date >= as_of

    def save(self, *args, **kwargs):
        if self.expiry_year is not None and self.expiry_month is not None:
            self.expiry_date = compute_expiry_date(two_digit_year=self.expiry_year, month=self.expiry_month)
        super().save(*args, **kwargs)


class EventLogQuerySet(models.QuerySet):
    def new_delinquent(self) -> models.QuerySet:
        return self.filter(type=EventLog.NEW_DELINQUENT)


class EventLog(models.Model):
    NEW_DELINQUENT = 'NEW_DELINQUENT'
    NEW_COMPLIANT = 'NEW_COMPLIANT'

    TYPES = (
        (NEW_DELINQUENT, 'New delinquent'),
        (NEW_COMPLIANT, 'New compliant'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True)
    account = models.ForeignKey(Account, on_delete=PROTECT, related_name='event_logs')
    type = models.CharField(max_length=20, choices=TYPES)
    text = models.CharField(max_length=255, blank=True)

    objects = EventLogQuerySet.as_manager()

    class Meta:
        verbose_name = _('event log')
        verbose_name_plural = _('event logs')
