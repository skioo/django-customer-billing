from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = 'billing'

    def ready(self):
        # noinspection PyUnresolvedReferences
        import billing.signals.handlers  # noqa: F401
