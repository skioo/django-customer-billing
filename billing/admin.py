from datetime import datetime

from django.conf.urls import url
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import ugettext_lazy as _
from moneyed.localization import format_money
from structlog import get_logger

from .actions import accounts, invoices
from .models import Account, Charge, CreditCard, Invoice, Transaction

logger = get_logger()


##############################################################
# Shared utilities


class AppendOnlyModelAdmin(admin.ModelAdmin):
    """
    Adapted from: https://gist.github.com/aaugustin/1388243
    """

    def get_readonly_fields(self, request, obj=None):
        # Make everything readonly (unless superuser)
        if request.user.is_superuser:
            return super().get_readonly_fields(request, obj)

        # We cannot call super().get_fields(request, obj) because that method calls
        # get_readonly_fields(request, obj), causing infinite recursion. Ditto for
        # super().get_form(request, obj). So we  assume the default ModelForm.

        f = self.fields or [f.name for f in self.model._meta.fields]
        f.extend(super().get_readonly_fields(request, obj))
        return f

    def has_change_permission(self, request, obj=None):
        # Allow viewing objects but not actually changing them (unless superuser)
        if request.user.is_superuser:
            return True
        return request.method in ['GET', 'HEAD'] and super().has_change_permission(request, obj)

    def get_actions(self, request):
        # Disable delete action (unless superuser)
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete link on detail page (unless superuser)
        return request.user.is_superuser


class ReadOnlyModelAdmin(AppendOnlyModelAdmin):
    def has_add_permission(self, request, obj=None):
        # Disable add link on admin menu and on list view (unless superuser)
        return request.user.is_superuser


account_owner_search_fields = ['account__owner__email', 'account__owner__first_name', 'account__owner__last_name']


def amount(obj):
    return format_money(obj.amount)


amount.admin_order_field = 'amount'  # type: ignore


def created_on(obj):
    return obj.created.date()


created_on.admin_order_field = 'created'  # type: ignore


def psp_admin_link(obj):
    text = '{}: {}'.format(obj.psp_content_type.name, obj.psp_object_id)
    url = reverse(
        'admin:{}_{}_change'.format(
            obj.psp_content_type.app_label,
            obj.psp_content_type.model),
        args=[obj.psp_object_id])
    return format_html('<a href="{}">{}</a>', url, text)


psp_admin_link.short_description = 'PSP Object'  # type: ignore


##############################################################
# Credit Cards

class CreditCardExpiredFilter(admin.SimpleListFilter):
    title = _('Expired')
    parameter_name = 'expired'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        today = datetime.now().date()
        if self.value() == 'yes':
            return queryset.filter(expiry_date__lt=today)
        if self.value() == 'no':
            return queryset.filter(expiry_date__gte=today)


def credit_card_expiry(obj):
    return format_html('{}/{}', obj.expiry_month, obj.expiry_year)


credit_card_expiry.admin_order_field = 'expiry_date'  # type: ignore


@admin.register(CreditCard)
class CreditCardAdmin(ReadOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['account', created_on, 'type', 'number', credit_card_expiry, psp_admin_link]
    search_fields = ['number'] + account_owner_search_fields
    list_filter = ['type', CreditCardExpiredFilter]
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified', 'expiry_date']


class CreditCardInline(admin.TabularInline):
    model = CreditCard
    fields = readonly_fields = ['type', 'number', credit_card_expiry, created_on, psp_admin_link]
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Charges

def charge_invoice(charge):
    i = charge.invoice
    if i is None:
        return _('Uninvoiced')
    else:
        text = str(i)
        url = reverse('admin:billing_invoice_change', args=(i.pk,))
        return format_html('<a href="{}">{}</a>', url, text)


charge_invoice.short_description = 'Invoice'  # type: ignore

charge_invoice.admin_order_field = 'invoice'  # type: ignore


@admin.register(Charge)
class ChargeAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['type', 'account', 'description', created_on, charge_invoice, amount]
    search_fields = ['amount', 'amount_currency', 'description', 'invoice__id'] + account_owner_search_fields
    list_filter = ['amount_currency']
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified']

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is not None and not obj.is_invoiced:
            return True
        return False


class ChargeInline(admin.TabularInline):
    verbose_name_plural = 'Charges and Credits'
    model = Charge
    fields = readonly_fields = ['type', 'description', created_on, charge_invoice, amount]
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


#############################################################
# Transactions

def transaction_invoice(transaction):
    i = transaction.invoice
    if i is not None:
        text = str(i)
        url = reverse('admin:billing_invoice_change', args=(i.pk,))
        return format_html('<a href="{}">{}</a>', url, text)


transaction_invoice.short_description = 'Invoice'  # type: ignore

transaction_invoice.admin_order_field = 'invoice'  # type: ignore


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyModelAdmin):
    verbose_name_plural = 'Transactions'
    date_hierarchy = 'created'
    list_display = ['type', 'account', 'payment_method', 'credit_card_number', created_on, 'success',
                    transaction_invoice, amount, psp_admin_link]
    list_display_links = ['type']
    search_fields = ['credit_card_number', 'amount'] + account_owner_search_fields
    list_filter = ['payment_method', 'success', 'amount_currency']
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified']


class TransactionInline(admin.TabularInline):
    model = Transaction
    fields = readonly_fields = ['type', 'payment_method', 'credit_card_number', created_on, 'success', amount,
                                psp_admin_link]
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Invoices

def pay_invoice_button(invoice):
    return format_html('<a href="{}">{}</a>',
                       reverse('admin:billing-pay-invoice', args=[invoice.pk]),
                       _('Pay Now'))


pay_invoice_button.short_description = _('Pay Invoice')  # type: ignore


def do_pay_invoice(request, invoice_id):
    invoices.pay(invoice_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


def invoice_number(invoice):
    return str(invoice)


invoice_number.short_description = 'Invoice'  # type: ignore

invoice_number.admin_order_field = 'pk'  # type: ignore


@admin.register(Invoice)
class InvoiceAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = [invoice_number, 'account', created_on, 'status', 'total']
    list_filter = ['status']
    search_fields = ['id', 'account__owner__email', 'account__owner__first_name', 'account__owner__last_name']
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified', 'total', pay_invoice_button]
    inlines = [ChargeInline, TransactionInline]

    def get_urls(self):
        custom_urls = [
            url(r'^(?P<invoice_id>.+)/pay/$',
                self.admin_site.admin_view(do_pay_invoice),
                name='billing-pay-invoice'),
        ]
        return custom_urls + super().get_urls()


class InvoiceInline(admin.TabularInline):
    model = Invoice
    readonly_fields = [invoice_number, created_on, 'status', 'total']
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Accounts

class AccountRatingFilter(admin.SimpleListFilter):
    title = _('Rating')
    parameter_name = 'rating'

    def lookups(self, request, model_admin):
        return (
            ('punctual', _('Punctual')),
            ('delinquent', _('Delinquent')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'punctual':
            return queryset.exclude(invoices__status=Invoice.PAST_DUE)
        if self.value() == 'delinquent':
            return queryset.filter(invoices__status=Invoice.PAST_DUE)


def punctual(self):
    return not self.has_past_due_invoices()


punctual.boolean = True  # type: ignore


def create_invoice_button(obj):
    return format_html(
        '<a class="button" href="{}">Create Invoice Now</a>',
        reverse('admin:billing-create-invoice', args=[obj.pk]),
    )


create_invoice_button.short_description = _('Create Invoice')  # type: ignore


def do_create_invoice(request, account_id):
    accounts.create_invoice_if_pending_charges(account_id=account_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


@admin.register(Account)
class AccountAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['owner', created_on, punctual, 'currency', 'status']
    search_fields = ['owner__email', 'owner__first_name', 'owner__last_name']
    list_filter = [AccountRatingFilter, 'currency', 'status']
    list_select_related = True

    raw_id_fields = ['owner']
    readonly_fields = ['balance', 'created', 'modified', create_invoice_button]

    inlines = [CreditCardInline, ChargeInline, InvoiceInline, TransactionInline]

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(
                r'^(?P<account_id>[0-9a-f-]+)/create_invoice/$',
                self.admin_site.admin_view(do_create_invoice),
                name='billing-create-invoice'
            )
        ]

        return my_urls + urls
