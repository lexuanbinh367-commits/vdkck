from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/diag/', views.api_diag, name='api_diag'),
    path('api/status/', views.api_status, name='api_status'),
    path('api/latest/', views.api_latest, name='api_latest'),
    path('api/history/', views.api_history, name='api_history'),
    path('api/alerts/', views.api_alerts, name='api_alerts'),
    path('api/command/', views.api_command, name='api_command'),
]
