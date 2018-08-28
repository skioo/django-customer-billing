from datetime import datetime, date

from django import forms
from django.conf.urls import url
from django.contrib import admin
from django.db.models import Max, Prefetch
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, NoReverseMatch
from django.utils.html import format_html, format_html_join
from django.utils.translation import ugettext_lazy as _
from moneyed.localization import format_money
from structlog import get_logger

from .actions import accounts, invoices
from .models import Account, Charge, CreditCard, Invoice, Transaction, ProductProperty

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
created_on.short_description = 'created'  # type: ignore


def modified_on(obj):
    return obj.modified.date()


modified_on.admin_order_field = 'modified'  # type: ignore
modified_on.short_description = 'modified'  # type: ignore


def psp_admin_link(obj):
    text = '{}: {}'.format(obj.psp_content_type.name, obj.psp_object_id)
    try:
        url = reverse(
            'admin:{}_{}_change'.format(
                obj.psp_content_type.app_label,
                obj.psp_content_type.model),
            args=[obj.psp_object_id])
        return format_html('<a href="{}">{}</a>', url, text)
    except NoReverseMatch:
        return None


psp_admin_link.short_description = 'PSP Object'  # type: ignore


def link_to_account(obj):
    account = obj.account
    text = str(account)
    url = reverse('admin:billing_account_change', args=(account.pk,))
    return format_html('<a href="{}">{}</a>', url, text)


link_to_account.admin_order_field = 'account'  # type: ignore
link_to_account.short_description = 'Account'  # type: ignore


def link_to_invoice(obj):
    invoice_id = obj.invoice_id
    if invoice_id is None:
        return '-'
    else:
        text = '#{}'.format(invoice_id)
        url = reverse('admin:billing_invoice_change', args=(invoice_id,))
        return format_html('<a href="{}">{}</a>', url, text)


link_to_invoice.admin_order_field = 'invoice'  # type: ignore
link_to_invoice.short_description = 'Invoice'  # type: ignore


##############################################################
# Credit Cards

class CreditCardValidFilter(admin.SimpleListFilter):
    title = _('Valid')
    parameter_name = 'valid'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        today = datetime.now().date()
        if self.value() == 'yes':
            return queryset.filter(expiry_date__gte=today)
        if self.value() == 'no':
            return queryset.filter(expiry_date__lt=today)


def credit_card_expiry(obj):
    return format_html('{}/{}', obj.expiry_month, obj.expiry_year)


credit_card_expiry.admin_order_field = 'expiry_date'  # type: ignore


def credit_card_is_valid(obj):
    return obj.is_valid()


credit_card_is_valid.boolean = True  # type: ignore

credit_card_is_valid.short_description = 'valid'  # type: ignore


@admin.register(CreditCard)
class CreditCardAdmin(ReadOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['number', created_on, link_to_account, 'type', 'status', credit_card_expiry,
                    credit_card_is_valid,
                    psp_admin_link]
    search_fields = ['number'] + account_owner_search_fields
    list_filter = ['type', 'status', CreditCardValidFilter]
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified', 'expiry_date']


class CreditCardInline(admin.TabularInline):
    model = CreditCard
    fields = readonly_fields = ['type', 'number', 'status', credit_card_expiry, created_on, psp_admin_link]
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Charges

def charge_deleted(charge):
    """
    We don't want to display a green check box to mean deleted.
    We use text instead to make sure there is no misinterpretation.
    """
    return 'Yes' if charge.deleted else 'No'


charge_deleted.short_description = 'Deleted'  # type: ignore

charge_deleted.admin_order_field = 'deleted'  # type: ignore


class ProductPropertyInline(admin.TabularInline):
    model = ProductProperty
    verbose_name_plural = 'Product props'
    ordering = ['name']


def product_properties(obj):
    return format_html_join(
        ',\n',
        '<strong>{}</strong>: {}',
        ((p.name, p.value) for p in obj.product_properties.all()))


product_properties.short_description = 'Product props'  # type: ignore


@admin.register(Charge)
class ChargeAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['type', created_on, charge_deleted, link_to_account, amount, 'product_code', product_properties,
                    'ad_hoc_label', link_to_invoice]
    search_fields = ['id', 'amount', 'amount_currency', 'product_code', 'product_properties__value', 'ad_hoc_label',
                     'invoice__id'] + account_owner_search_fields
    list_filter = ['deleted', 'amount_currency', 'product_code']
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account', 'invoice', 'reverses']
    readonly_fields = ['created', 'modified']
    inlines = [ProductPropertyInline]

    def get_queryset(self, request):
        # In this particular admin screen we want to see even the deleted charges
        qs = Charge.all_charges
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs \
            .prefetch_related('invoice') \
            .prefetch_related('product_properties')


class ChargeInline(admin.TabularInline):
    verbose_name_plural = 'Charges and Credits'
    model = Charge
    fields = readonly_fields = ['type', created_on, link_to_invoice, amount, 'product_code', product_properties,
                                'ad_hoc_label']
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('product_properties')


#############################################################
# Transactions

@admin.register(Transaction)
class TransactionAdmin(ReadOnlyModelAdmin):
    verbose_name_plural = 'Transactions'
    date_hierarchy = 'created'
    list_display = ['type', created_on, link_to_account, 'payment_method', 'credit_card_number', 'success',
                    link_to_invoice, amount, psp_admin_link]
    list_display_links = ['type']
    search_fields = ['credit_card_number', 'amount'] + account_owner_search_fields
    list_filter = ['payment_method', 'success', 'amount_currency']
    ordering = ['-created']
    list_select_related = True

    raw_id_fields = ['account', 'invoice']
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

class InvoiceOverdueFilter(admin.SimpleListFilter):
    title = _('Overdue')
    parameter_name = 'overdue'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        today = datetime.now().date()
        if self.value() == 'yes':
            return queryset.filter(due_date__lt=today)
        if self.value() == 'no':
            return queryset.filter(due_date__gte=today)


class InvoiceValidCCFilter(admin.SimpleListFilter):
    title = _('Valid cc')
    parameter_name = 'valid_cc'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        d = date.today()
        if self.value() == 'yes':
            return queryset.filter(account__credit_cards__expiry_date__gte=d)
        if self.value() == 'no':
            return queryset.exclude(account__credit_cards__expiry_date__gte=d)


def pay_invoice_button(obj):
    if obj.pk and obj.in_payable_state:
        return format_html(
            '<a href="{}">Pay Now</a>',
            reverse('admin:billing-pay-invoice', args=[obj.pk]))
    else:
        return '-'


pay_invoice_button.short_description = _('Pay Invoice')  # type: ignore


def do_pay_invoice(request, invoice_id):
    invoices.pay_with_account_credit_cards(invoice_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


def invoice_number(invoice):
    return str(invoice)


invoice_number.short_description = 'Invoice'  # type: ignore

invoice_number.admin_order_field = 'pk'  # type: ignore


def invoice_last_transaction(obj):
    dt = obj.last_transaction
    if dt:
        return dt.date()


invoice_last_transaction.short_description = 'Last transaction'  # type: ignore


def invoice_account_has_valid_cc(obj):
    return len(obj.account.valid_credit_card_ids) != 0


invoice_account_has_valid_cc.short_description = 'Valid cc'  # type: ignore

invoice_account_has_valid_cc.boolean = True  # type: ignore


@admin.register(Invoice)
class InvoiceAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = [invoice_number, created_on, link_to_account, invoice_account_has_valid_cc, 'total',
                    'due_date', invoice_last_transaction, 'status']
    list_filter = [InvoiceValidCCFilter, InvoiceOverdueFilter, 'status']
    search_fields = ['id', 'account__owner__email', 'account__owner__first_name', 'account__owner__last_name']
    ordering = ['-created']

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified', 'total', pay_invoice_button]
    inlines = [ChargeInline, TransactionInline]

    def get_queryset(self, request):
        return super().get_queryset(request) \
            .select_related('account__owner') \
            .annotate(last_transaction=Max('transactions__created')) \
            .prefetch_related(Prefetch('account__credit_cards',
                                       queryset=CreditCard.objects.valid(),
                                       to_attr='valid_credit_card_ids'))

    def get_urls(self):
        custom_urls = [
            url(r'^(?P<invoice_id>[0-9a-f-]+)/pay/$',
                self.admin_site.admin_view(do_pay_invoice),
                name='billing-pay-invoice'),
        ]
        return custom_urls + super().get_urls()


class InvoiceInline(admin.TabularInline):
    model = Invoice
    readonly_fields = [invoice_number, created_on, 'status', 'due_date', 'total']
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Accounts

class AccountHasValidCCFilter(admin.SimpleListFilter):
    title = _('Has valid cc')
    parameter_name = 'Has_valid_cc'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        d = date.today()
        if self.value() == 'yes':
            return queryset.filter(credit_cards__expiry_date__gte=d)
        if self.value() == 'no':
            return queryset.exclude(credit_cards__expiry_date__gte=d)


def payable_invoice_count(obj):
    return len(obj.payable_invoice_ids)


def has_valid_cc(obj):
    return len(obj.valid_credit_card_ids) != 0


has_valid_cc.boolean = True  # type: ignore


def create_invoices_button(obj):
    if obj.pk:
        return format_html(
            '<a class="button" href="{}">Create Invoices</a>',
            reverse('admin:billing-create-invoices', args=[obj.pk]),
        )
    else:
        return '-'


create_invoices_button.short_description = _('Create Invoices')  # type: ignore


class CreateInvoicesForm(forms.Form):
    due_date = forms.DateField()


def create_invoices_form(request, account_id):
    form = CreateInvoicesForm(request.POST or None, initial={'due_date': date.today()})
    if request.method == 'POST':
        if form.is_valid():
            accounts.create_invoices(
                account_id=account_id,
                due_date=form.cleaned_data['due_date'])
            # As confirmation take the user to the account overview.
            return HttpResponseRedirect(reverse('admin:billing_account_change', args=[account_id]))

    return render(
        request,
        'admin/billing/form.html',
        {
            'title': 'Create invoices',
            'form': form,
            'opts': Account._meta,  # Used to setup the navigation / breadcrumbs of the page
        }
    )


def do_create_invoices(request, account_id):
    accounts.create_invoices(account_id=account_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


@admin.register(Account)
class AccountAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = ['owner', created_on, modified_on, payable_invoice_count, has_valid_cc, 'currency', 'status']
    search_fields = ['id', 'owner__email', 'owner__first_name', 'owner__last_name']
    ordering = ['-created']
    list_filter = [AccountHasValidCCFilter, 'currency', 'status']
    list_select_related = True

    raw_id_fields = ['owner']
    readonly_fields = ['balance', 'created', 'modified', create_invoices_button]

    inlines = [CreditCardInline, ChargeInline, InvoiceInline, TransactionInline]

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(
                r'^(?P<account_id>[0-9a-f-]+)/create_invoices/$',
                self.admin_site.admin_view(create_invoices_form),
                name='billing-create-invoices'
            )
        ]
        return my_urls + urls

    def get_queryset(self, request):
        return super().get_queryset(request) \
            .prefetch_related(Prefetch('invoices',
                                       queryset=Invoice.objects.payable().only('id'),
                                       to_attr='payable_invoice_ids')) \
            .prefetch_related(Prefetch('credit_cards',
                                       queryset=CreditCard.objects.valid().only('id'),
                                       to_attr='valid_credit_card_ids'))
