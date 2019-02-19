from import_export import resources
from import_export.fields import Field

from .models import Invoice


class InvoiceResource(resources.ModelResource):
    """
    We take precise control of the output:
    - The due amount in two separate columns (the number column and the currency column).

    TODO: Compute due() only once per invoice. Then maybe add invoice.total().
    """
    due_amount = Field()
    due_amount_currency = Field()

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
        due_total_monies = invoice.due().monies()
        if len(due_total_monies) == 1:
            due_total = due_total_monies[0]
            return due_total
