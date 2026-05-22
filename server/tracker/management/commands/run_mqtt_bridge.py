"""
MQTT bridge (tuy chon - mac dinh tu bat khi runserver).
Chi can khi debug: python manage.py run_mqtt_bridge
Truoc do chay CHAY.bat de mo Mosquitto.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from tracker.mqtt_service import start_mqtt_bridge


class Command(BaseCommand):
    help = 'Khoi dong MQTT bridge (nhan telemetry ESP, luu MySQL)'

    def handle(self, *args, **options):
        host = settings.MQTT_BROKER_HOST
        port = settings.MQTT_BROKER_PORT
        self.stdout.write(self.style.SUCCESS(
            f'Dang ket noi MQTT broker {host}:{port} ...'
        ))
        self.stdout.write(
            'Neu loi 10061: chua co broker. Mo terminal khac, chay:\n'
            '  powershell -ExecutionPolicy Bypass -File scripts\\start_mosquitto.ps1\n'
        )

        def on_status(connected, message):
            if connected:
                self.stdout.write(self.style.SUCCESS(message))
            else:
                self.stdout.write(self.style.WARNING(message))

        start_mqtt_bridge(on_status=on_status)
