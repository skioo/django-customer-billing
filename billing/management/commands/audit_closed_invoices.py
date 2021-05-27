import logging

import structlog
from django.core.management.base import BaseCommand

from ...actions.invoices import audit_closed_invoices


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
        audit_closed_invoices()
