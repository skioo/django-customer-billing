from django.conf.urls import url

from .views import AccountView

urlpatterns = [
    url(r'^account/$', AccountView.as_view(), name='billing_account'),
]
