from django.dispatch import Signal

# We want to signal when an invoice was created and is ready to be looked at.
# (we cannot use the built-in post_save signal for that because just after an
# invoice is saved it doesn't yet have charges attached)
invoice_ready = Signal(providing_args=['invoice'], use_caching=True)

update_delinquents_command_executed = Signal(
    providing_args=['new_delinquent_accounts_map', 'compliant_accounts_ids']
)
