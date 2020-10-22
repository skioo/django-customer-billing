from django.dispatch import Signal

# We want to signal when an invoice was created and is ready to be looked at.
# (we cannot use the built-in post_save signal for that because just after an
# invoice is saved it doesn't yet have charges attached)
invoice_ready = Signal(providing_args=['invoice'], use_caching=True)

credit_card_registered = Signal(providing_args=['credit_card'])

new_delinquent_account = Signal(providing_args=['account', 'reason'])

new_compliant_account = Signal(providing_args=['account', 'reason'])
