from django.conf.urls import url
from rest_framework import routers

from .views import AccountView, CreditCardViewSet

router = routers.SimpleRouter(trailing_slash=False)
router.register(r'account/credit-cards', CreditCardViewSet, basename='billing_creditcard')

urlpatterns = router.urls + [
    url(r'^account$', AccountView.as_view(), name='billing_account'),
]
