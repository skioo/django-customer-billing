from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = 'billing'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # noinspection PyUnresolvedReferences
        import billing.signals.handlers  # noqa: F401
