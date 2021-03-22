from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(r'^billing/', include('billing.urls')),
    path(r'^admin/', admin.site.urls),
]
