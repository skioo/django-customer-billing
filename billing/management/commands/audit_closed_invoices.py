import logging

import structlog
from django.core.management.base import BaseCommand

from ...models import Invoice


def set_debug(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


logger = structlog.get_logger()


class Command(BaseCommand):
    help = """Displays all paid and cancelled invoices where due != 0"""

    def handle(self, *args, **options):
        if options['verbosity'] >= 2:
            set_debug('django.db.backends')

        invoices = Invoice.objects.exclude(status=Invoice.PENDING)

        logger.debug('audit-closed-invoices', non_pending_invoice_count=len(invoices))

        for invoice in invoices:
            due_total = invoice.due()
            due_monies = due_total.monies()
            if len(due_monies) != 1:
                logger.info('wrong-number-of-currencies', invoice_id=invoice.id, status=invoice.status,
                            currency_count=len(due_monies))
                continue
            due_value = due_monies[0]
            if due_value.amount != 0:
                logger.info('non-zero-due', invoice_id=invoice.id, status=invoice.status, due=due_value)
