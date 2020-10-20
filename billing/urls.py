
from django.urls import path
from rest_framework import routers

from .views import (
    AccountView,
    CreditCardViewSet,
    pay_open_invoices_with_registered_credit_cards,
)

router = routers.SimpleRouter(trailing_slash=False)
router.register(
    r'account/credit-cards',
    CreditCardViewSet,
    basename='billing_creditcard'
)

urlpatterns = router.urls + [
    path('account', AccountView.as_view(), name='billing_account'),
    path(
        'pay/open/invoices/with/registered/credit/cards',
        pay_open_invoices_with_registered_credit_cards,
        name='pay_open_invoices_with_registered_credit_cards'
    ),
]
