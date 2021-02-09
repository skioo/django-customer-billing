from datetime import date, datetime

from django import forms
from django.conf.urls import url
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from import_export.formats import base_formats
from moneyed.localization import format_money
from structlog import get_logger
from typing import Dict

from .actions import accounts, invoices
from .models import (
    Account, Charge, CreditCard, EventLog, Invoice, ProductProperty,
    Transaction,
)

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
            if 'delete_selected' in actions:
                del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        # Disable delete link on detail page (unless superuser)
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
    if obj.psp_content_type is None or obj.psp_object_id is None:
        return '-'

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
class CreditCardAdmin(AppendOnlyModelAdmin):
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

class TransactionResource(resources.ModelResource):
    amount = Field()
    amount_currency = Field()

    class Meta:
        model = Transaction
        fields = ['id', 'created', 'modified', 'success', 'payment_method',
                  'credit_card_number', 'account__owner__email', 'invoice']

    def dehydrate_amount(self, tx):
        if tx.amount is not None:
            return tx.amount.amount

    def dehydrate_amount_currency(self, tx):
        if tx.amount is not None:
            return tx.amount.currency.code


@admin.register(Transaction)
class TransactionAdmin(ExportMixin, AppendOnlyModelAdmin):
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

    # Export
    resource_class = TransactionResource
    formats = (base_formats.CSV, base_formats.XLS, base_formats.JSON)  # Safe and useful formats.


class TransactionInline(admin.TabularInline):
    model = Transaction
    fields = readonly_fields = ['type', 'payment_method', 'credit_card_number', created_on, 'success', amount,
                                link_to_invoice, psp_admin_link]
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


##############################################################
# Invoices

class InvoiceResource(resources.ModelResource):
    """
    We separate the due amount into number and currency columns to make processing the exported data easier.
    Calculating the due amount is costly and we don't want to do it twice so we cache it.
    """
    due_amount = Field()
    due_amount_currency = Field()

    cc = Field()

    due_cache: Dict = {}

    class Meta:
        model = Invoice
        fields = ['id', 'account__owner__email', 'created', 'modified', 'due_date', 'status']

    def dehydrate_due_amount(self, invoice):
        due = self._due(invoice)
        if due is not None:
            return due.amount

    def dehydrate_due_amount_currency(self, invoice):
        due = self._due(invoice)
        if due is not None:
            return due.currency.code

    def _due(self, invoice):
        cached = self.due_cache.get(invoice.id)
        if cached:
            return cached
        due = self.calculate_due(invoice)
        self.due_cache[invoice.id] = due
        return due

    def calculate_due(self, invoice):
        due_total_monies = invoice.due().monies()
        if len(due_total_monies) == 1:
            due_total = due_total_monies[0]
            return due_total

    def dehydrate_cc(self, invoice):
        return invoice_account_cc(invoice)


class InvoiceDueFilter(admin.SimpleListFilter):
    title = _('Due')
    parameter_name = 'due'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        today = datetime.now().date()
        if self.value() == 'yes':
            return queryset.filter(due_date__lte=today)
        if self.value() == 'no':
            return queryset.filter(due_date__gt=today)


class InvoiceCCFilter(admin.SimpleListFilter):
    title = _('cc')
    parameter_name = 'cc'

    def lookups(self, request, model_admin):
        return (
            ('valid', _('Valid')),
            ('expired', _('Expired')),
            ('none', _('None')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        d = date.today()
        if self.value() == 'valid':
            return queryset.filter(account__credit_cards__expiry_date__gte=d)
        if self.value() == 'expired':
            return queryset.exclude(account__credit_cards__expiry_date__gte=d) \
                .exclude(account__credit_cards=None)
        if self.value() == 'none':
            return queryset.filter(account__credit_cards=None)


def assign_funds_to_invoice_button(obj):
    if obj.pk and obj.in_payable_state:
        return format_html(
            '<a href="{}">Assign existing funds to invoice</a>',
            reverse('admin:billing-assign-funds-to-invoice', args=[obj.pk]))
    else:
        return '-'


assign_funds_to_invoice_button.short_description = _('Assign funds')  # type: ignore


def do_assign_funds_to_invoice(request, invoice_id):
    accounts.assign_funds_to_invoice(invoice_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


def pay_invoice_with_cc_button(obj):
    if obj.pk and obj.in_payable_state:
        return format_html(
            '<a href="{}">Pay invoice with CC</a>',
            reverse('admin:billing-pay-invoice-with-cc', args=[obj.pk]))
    else:
        return '-'


pay_invoice_with_cc_button.short_description = _('Pay')  # type: ignore


def do_pay_invoice_with_cc(request, invoice_id):
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


def invoice_account_cc(obj):
    if obj.valid_credit_card_count > 0:
        return 'Valid'
    elif obj.credit_card_count > 0:
        return 'Expired'
    else:
        return 'None'


invoice_account_cc.short_description = 'cc'  # type: ignore


@admin.register(Invoice)
class InvoiceAdmin(ExportMixin, AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = [invoice_number, created_on, modified_on, link_to_account, invoice_account_cc,
                    'total_charges', 'due', 'due_date', invoice_last_transaction, 'status']
    list_filter = [InvoiceCCFilter, InvoiceDueFilter, 'status']
    search_fields = ['id', 'account__owner__email', 'account__owner__first_name', 'account__owner__last_name']
    ordering = ['-created']

    raw_id_fields = ['account']
    readonly_fields = ['created', 'modified', 'total_charges', 'due', assign_funds_to_invoice_button,
                       pay_invoice_with_cc_button]
    inlines = [ChargeInline, TransactionInline]

    # Export
    resource_class = InvoiceResource
    formats = (base_formats.CSV, base_formats.XLS, base_formats.JSON)  # Safe and useful formats.

    def get_queryset(self, request):
        return super().get_queryset(request) \
            .select_related('account__owner') \
            .annotate(last_transaction=Max('transactions__created')) \
            .annotate(
            credit_card_count=Count('account__credit_cards'),
            valid_credit_card_count=Count('account__credit_cards',
                                          filter=Q(account__credit_cards__expiry_date__gte=date.today()))) \
            .only('id', 'created', 'modified', 'account__owner__email', 'account__owner__id', 'due_date', 'status')

    def get_urls(self):
        custom_urls = [
            url(r'^(?P<invoice_id>[0-9a-f-]+)/assign_funds_to_invoice/$',
                self.admin_site.admin_view(do_assign_funds_to_invoice),
                name='billing-assign-funds-to-invoice'),
            url(r'^(?P<invoice_id>[0-9a-f-]+)/pay/$',
                self.admin_site.admin_view(do_pay_invoice_with_cc),
                name='billing-pay-invoice-with-cc')
        ]
        return custom_urls + super().get_urls()

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if 'status' in form.changed_data:
            self.manage_update_status(obj, request)
        super().save_model(request, obj, form, change)

    def manage_update_status(self, invoice: Invoice, request: HttpRequest):
        previous_status = Invoice.objects.get(id=invoice.id).status
        new_status = invoice.status

        if previous_status == Invoice.PENDING and new_status == Invoice.CANCELLED:
            self.manage_invoice_cancellation(invoice, request)

        if previous_status == Invoice.CANCELLED and new_status == Invoice.PENDING:
            self.manage_invoice_reverse_cancellation(invoice, request)

    @staticmethod
    def manage_invoice_cancellation(invoice: Invoice, request: HttpRequest):
        reverse_charges = Charge.objects.filter(invoice=invoice, reverses__isnull=False)
        negative_charges = Charge.objects.filter(invoice=invoice, amount__lte=0)

        if invoice.is_partially_paid():
            messages.add_message(
                request,
                messages.WARNING,
                'Cancellation consequences have not been managed automatically because '
                'invoice is partially paid. Manage them manually.'
            )
            return

        if reverse_charges:
            messages.add_message(
                request,
                messages.WARNING,
                'Cancellation consequences have not been managed automatically because '
                'invoice already has reverse charges. Manage them manually.'
            )
            return

        if negative_charges:
            messages.add_message(
                request,
                messages.WARNING,
                'Cancellation consequences have not been managed automatically because '
                'invoice has negative charges. Manage them manually.'
            )
            return

        charges = Charge.objects.filter(invoice=invoice)
        for charge in charges:
            Charge.objects.create(
                account=charge.account,
                invoice=invoice,
                amount=-charge.amount,
                reverses=charge,
                ad_hoc_label=charge.ad_hoc_label,
                product_code=charge.product_code
            )
        messages.add_message(
            request,
            messages.SUCCESS,
            'Cancellation consequences managed automatically'
        )

    @staticmethod
    def manage_invoice_reverse_cancellation(invoice: Invoice, request: HttpRequest):
        reverse_charges = Charge.objects.filter(invoice=invoice, reverses__isnull=False)
        no_reverse_charges = Charge.objects.filter(
            invoice=invoice,
            reverses__isnull=True
        )

        if invoice.is_partially_paid():
            messages.add_message(
                request,
                messages.WARNING,
                'Reverse cancellation consequences have not been managed automatically '
                'because invoice is partially paid. Manage them manually.'
            )
            return

        if reverse_charges.count() != no_reverse_charges.count():
            messages.add_message(
                request,
                messages.WARNING,
                'Reverse cancellation consequences have not been managed automatically '
                'because invoice reverse and no reverse charges are not the same number'
                '. Manage them manually.'
            )
            return

        reverse_charges.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            'Reverse cancellation consequences managed automatically'
        )


class InvoiceInline(admin.TabularInline):
    model = Invoice
    readonly_fields = [invoice_number, created_on, 'status', 'due_date', 'total_charges', 'due']
    show_change_link = True
    can_delete = False
    extra = 0
    ordering = ['-created']


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'type', 'text', link_to_account)
    ordering = ('-created',)
    list_display_links = None
    list_filter = ('type',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('account')

    def has_add_permission(self, request):
        return False


class EventLogInline(admin.TabularInline):
    model = EventLog
    readonly_fields = ('created', 'type', 'text')
    show_change_link = False
    can_delete = False
    extra = 0
    ordering = ('-created',)


##############################################################
# Accounts

class AccountCCFilter(admin.SimpleListFilter):
    title = _('cc')
    parameter_name = 'cc'

    def lookups(self, request, model_admin):
        return (
            ('valid', _('Valid')),
            ('expired', _('Expired')),
            ('none', _('None')),
            ('all', _('All')),
        )

    def queryset(self, request, queryset):
        d = date.today()
        if self.value() == 'valid':
            return queryset.filter(credit_cards__expiry_date__gte=d)
        if self.value() == 'expired':
            return queryset.exclude(credit_cards__expiry_date__gte=d) \
                .exclude(credit_cards=None)
        if self.value() == 'none':
            return queryset.filter(credit_cards=None)


def payable_invoice_count(obj):
    return len(obj.payable_invoice_ids)


def account_cc(obj):
    if obj.valid_credit_card_count > 0:
        return 'Valid'
    elif obj.credit_card_count > 0:
        return 'Expired'
    else:
        return 'None'


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


def assign_funds_to_pending_invoices_button(obj):
    if obj.pk:
        return format_html(
            '<a class="button" href="{}">Assign existing funds to pending invoices</a>',
            reverse('admin:billing-assign-funds-to-pending-invoices', args=[obj.pk]),
        )
    else:
        return '-'


assign_funds_to_pending_invoices_button.short_description = _('Assign funds')  # type: ignore


def do_assign_funds_to_pending_invoices(request, account_id):
    accounts.assign_funds_to_account_pending_invoices(account_id=account_id)
    return HttpResponseRedirect(request.META.get('HTTP_REFERER'))


@admin.register(Account)
class AccountAdmin(AppendOnlyModelAdmin):
    date_hierarchy = 'created'
    list_display = [
        'owner', created_on, modified_on, payable_invoice_count, account_cc, 'currency',
        'status', 'delinquent'
    ]
    search_fields = ['id', 'owner__email', 'owner__first_name', 'owner__last_name']
    ordering = ['-created']
    list_filter = [AccountCCFilter, 'currency', 'status']
    list_select_related = True

    raw_id_fields = ['owner']
    readonly_fields = ['balance', 'created', 'modified', create_invoices_button,
                       assign_funds_to_pending_invoices_button]

    inlines = [
        CreditCardInline,
        ChargeInline,
        InvoiceInline,
        TransactionInline,
        EventLogInline
    ]

    def save_model(self, request, obj, form, change):
        if 'delinquent' in form.changed_data:
            if obj.delinquent:
                accounts.mark_account_as_delinquent(obj.id, reason='Manually')
            else:
                accounts.mark_account_as_compliant(obj.id, reason='Manually')
        super().save_model(request, obj, form, change)

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(
                r'^(?P<account_id>[0-9a-f-]+)/create_invoices/$',
                self.admin_site.admin_view(create_invoices_form),
                name='billing-create-invoices'
            ), url(
                r'^(?P<account_id>[0-9a-f-]+)/assign_funds_to_pending_invoices/$',
                self.admin_site.admin_view(do_assign_funds_to_pending_invoices),
                name='billing-assign-funds-to-pending-invoices'
            )
        ]
        return my_urls + urls

    def get_queryset(self, request):
        return super().get_queryset(request) \
            .prefetch_related(Prefetch('invoices',
                                       queryset=Invoice.objects.payable().only('id'),
                                       to_attr='payable_invoice_ids')) \
            .annotate(
            credit_card_count=Count('credit_cards'),
            valid_credit_card_count=Count('credit_cards', filter=Q(credit_cards__expiry_date__gte=date.today())))
