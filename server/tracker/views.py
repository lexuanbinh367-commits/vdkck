import json
import socket

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import Alert, SensorReading, SystemState
from . import mqtt_service


def dashboard(request):
    return render(request, 'dashboard.html')


@require_GET
def api_diag(request):
    """Kiem tra broker MQTT va trang thai ESP."""
    device_id = request.GET.get('device', 'solar_tracker_01')
    broker_host = settings.MQTT_BROKER_HOST
    broker_port = settings.MQTT_BROKER_PORT

    port_open = False
    listen_addresses = []
    try:
        import subprocess
        result = subprocess.run(
            ['netstat', '-an'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if ':1883' in line and 'LISTENING' in line.upper():
                listen_addresses.append(line.strip())
    except Exception:
        pass

    try:
        with socket.create_connection((broker_host, broker_port), timeout=2):
            port_open = True
    except OSError:
        port_open = False

    # Mosquitto chi lang nghe 127.0.0.1 -> ESP trong mang khong ket noi duoc
    only_localhost = bool(listen_addresses) and all(
        '127.0.0.1:1883' in a or '[::1]:1883' in a for a in listen_addresses
    ) and not any('0.0.0.0:1883' in a for a in listen_addresses)

    try:
        state = SystemState.objects.get(device_id=device_id)
        last_seen = state.last_seen.isoformat() if state.last_seen else None
        online = state.online
        if state.last_seen:
            age = (timezone.now() - state.last_seen).total_seconds()
            if age > settings.ALERT_OFFLINE_SECONDS:
                online = False
    except SystemState.DoesNotExist:
        state = None
        online = False
        last_seen = None

    reading_count = SensorReading.objects.filter(device_id=device_id).count()

    hints = []
    if not port_open:
        hints.append('Mosquitto chua chay. Chay: scripts/start_mosquitto.ps1')
    if only_localhost:
        hints.append(
            'LOI THUONG GAP: Mosquitto chi lang nghe 127.0.0.1. '
            'ESP khong ket noi duoc! Dung scripts/start_mosquitto.ps1 thay vi net start mosquitto'
        )
    if port_open and not online:
        hints.append('Trong file .ino: MQTT_SERVER = IP may tinh (ipconfig), hien tai ESP can ket noi toi may tinh')
        hints.append('Mo firewall port 1883: scripts/fix_esp_mqtt.ps1 (Admin)')
        hints.append('Serial Monitor 115200: can thay ">>> MQTT KET NOI THANH CONG <<<"')
    if online:
        hints.append('ESP dang ket noi binh thuong')

    return JsonResponse({
        'broker': f'{broker_host}:{broker_port}',
        'broker_port_open': port_open,
        'mqtt_listen': listen_addresses,
        'mqtt_only_localhost': only_localhost,
        'esp_online': online,
        'last_seen': last_seen,
        'readings_saved': reading_count,
        'hints': hints,
    })

@require_GET
def api_status(request):
    device_id = request.GET.get('device', 'solar_tracker_01')
    try:
        state = SystemState.objects.get(device_id=device_id)
        online = state.online
        if state.last_seen:
            age = (timezone.now() - state.last_seen).total_seconds()
            if age > settings.ALERT_OFFLINE_SECONDS:
                online = False
    except SystemState.DoesNotExist:
        state = None
        online = False

    return JsonResponse({
        'online': online,
        'device_id': device_id,
        'mode': state.mode if state else 'auto',
        'azimuth': state.azimuth if state else 0,
        'elevation': state.elevation if state else 0,
        'target_azimuth': state.target_azimuth if state else 90,
        'target_elevation': state.target_elevation if state else 90,
        'light_total': state.light_total if state else 0,
        'last_seen': state.last_seen.isoformat() if state and state.last_seen else None,
    })


@require_GET
def api_latest(request):
    device_id = request.GET.get('device', 'solar_tracker_01')
    reading = SensorReading.objects.filter(device_id=device_id).first()
    if not reading:
        return JsonResponse({'reading': None})

    return JsonResponse({
        'reading': {
            'timestamp': reading.timestamp.isoformat(),
            'ldr_tl': reading.ldr_tl,
            'ldr_tr': reading.ldr_tr,
            'ldr_bl': reading.ldr_bl,
            'ldr_br': reading.ldr_br,
            # Orientation mapping for UI convenience
            'ldr_east': reading.ldr_tl,
            'ldr_west': reading.ldr_tr,
            'ldr_north': reading.ldr_bl,
            'ldr_south': reading.ldr_br,
            'light_total': reading.light_total,
            'azimuth': reading.azimuth,
            'elevation': reading.elevation,
            'mode': reading.mode,
        }
    })


@require_GET
def api_history(request):
    device_id = request.GET.get('device', 'solar_tracker_01')
    limit = min(int(request.GET.get('limit', 100)), 500)
    hours = request.GET.get('hours')

    qs = SensorReading.objects.filter(device_id=device_id)
    if hours:
        since = timezone.now() - timezone.timedelta(hours=float(hours))
        qs = qs.filter(timestamp__gte=since)

    readings = qs.order_by('-timestamp')[:limit]
    data = [
        {
            'timestamp': r.timestamp.isoformat(),
            'ldr_tl': r.ldr_tl,
            'ldr_tr': r.ldr_tr,
            'ldr_bl': r.ldr_bl,
            'ldr_br': r.ldr_br,
            # add orientation aliases for front-end
            'ldr_east': r.ldr_tl,
            'ldr_west': r.ldr_tr,
            'ldr_north': r.ldr_bl,
            'ldr_south': r.ldr_br,
            'light_total': r.light_total,
            'azimuth': r.azimuth,
            'elevation': r.elevation,
            'mode': r.mode,
        }
        for r in reversed(list(readings))
    ]
    return JsonResponse({'readings': data})


@require_GET
def api_alerts(request):
    device_id = request.GET.get('device', 'solar_tracker_01')
    limit = min(int(request.GET.get('limit', 20)), 100)
    alerts = Alert.objects.filter(device_id=device_id).order_by('-timestamp')[:limit]
    return JsonResponse({
        'alerts': [
            {
                'id': a.id,
                'timestamp': a.timestamp.isoformat(),
                'severity': a.severity,
                'alert_type': a.alert_type,
                'message': a.message,
                'acknowledged': a.acknowledged,
            }
            for a in alerts
        ]
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_command(request):
    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON không hợp lệ'}, status=400)

    mode = body.get('mode', 'auto')
    azimuth = int(body.get('azimuth', 90))
    elevation = int(body.get('elevation', 90))

    device_id = body.get('device', 'solar_tracker_01')

    # Luu che do ngay ca khi MQTT bridge chua chay (ESP offline)
    SystemState.objects.update_or_create(
        device_id=device_id,
        defaults={
            'mode': mode,
            'target_azimuth': azimuth,
            'target_elevation': elevation,
        },
    )

    try:
        payload = mqtt_service.publish_command(mode, azimuth, elevation)
    except RuntimeError as e:
        return JsonResponse({
            'ok': True,
            'mode_saved': True,
            'mqtt_sent': False,
            'warning': str(e),
        })

    return JsonResponse({'ok': True, 'mqtt_sent': True, 'payload': payload})
