
from django.urls import path
from rest_framework import routers

from .views import AccountView, CreditCardViewSet, pay_debt

router = routers.SimpleRouter(trailing_slash=False)
router.register(
    r'account/credit-cards',
    CreditCardViewSet,
    basename='billing_creditcard'
)

urlpatterns = router.urls + [
    path('account', AccountView.as_view(), name='billing_account'),
    path('pay/debt', pay_debt, name='pay_debt'),
]
