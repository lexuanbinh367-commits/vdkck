from django.contrib import admin
from .models import Alert, SensorReading, SystemState


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'timestamp', 'light_total', 'azimuth', 'elevation', 'mode')
    list_filter = ('device_id', 'mode')
    readonly_fields = ('timestamp',)


@admin.register(SystemState)
class SystemStateAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'online', 'last_seen', 'mode', 'azimuth', 'elevation')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'device_id', 'severity', 'alert_type', 'message', 'acknowledged')
    list_filter = ('severity', 'acknowledged')
