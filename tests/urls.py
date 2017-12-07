from django.conf.urls import include, url
from django.contrib import admin

urlpatterns = [
    url(r'^billing/', include('billing.urls')),
    url(r'^admin/', admin.site.urls),
]
