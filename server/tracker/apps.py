import os
import sys
import threading

from django.apps import AppConfig
from django.conf import settings


class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'
    verbose_name = 'Giám sát năng lượng mặt trời'

    _bridge_started = False

    def ready(self):
        if not getattr(settings, 'MQTT_BRIDGE_AUTOSTART', True):
            return
        if 'runserver' not in sys.argv:
            return
        if os.environ.get('RUN_MAIN') != 'true':
            return
        if TrackerConfig._bridge_started:
            return
        TrackerConfig._bridge_started = True

        def run_bridge():
            from .mqtt_service import start_mqtt_bridge
            start_mqtt_bridge()

        threading.Thread(target=run_bridge, daemon=True, name='mqtt-bridge').start()
