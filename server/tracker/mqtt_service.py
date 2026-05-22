"""
MQTT bridge: nhận telemetry từ ESP, lưu DB, phát hiện cảnh báo, gửi lệnh điều khiển.
"""
import json
import logging
import threading
from datetime import timedelta

import paho.mqtt.client as mqtt
from django.conf import settings
from django.utils import timezone

from .models import Alert, SensorReading, SystemState

logger = logging.getLogger(__name__)

_last_reading = {}  # device_id -> SensorReading instance (cache cho so sánh)


def _parse_json(payload: str):
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _check_anomalies(device_id: str, data: dict, reading: SensorReading):
    """Phát hiện và lưu cảnh báo bất thường."""
    alerts = []
    light = data.get('light_total', 0)
    az = data.get('azimuth', 0)
    el = data.get('elevation', 0)

    if light < settings.ALERT_LIGHT_MIN:
        alerts.append(('light_low', 'warning', f'Ánh sáng quá thấp: {light}'))

    if light > settings.ALERT_LIGHT_MAX:
        alerts.append(('light_high', 'warning', f'Ánh sáng bất thường cao: {light}'))

    prev = _last_reading.get(device_id)
    if prev:
        if abs(az - prev.azimuth) > settings.ALERT_ANGLE_JUMP:
            alerts.append((
                'angle_jump_az',
                'warning',
                f'Góc azimuth nhảy đột ngột: {prev.azimuth}° → {az}°',
            ))
        if abs(el - prev.elevation) > settings.ALERT_ANGLE_JUMP:
            alerts.append((
                'angle_jump_el',
                'warning',
                f'Góc elevation nhảy đột ngột: {prev.elevation}° → {el}°',
            ))

    # rain sensor removed — no rain-related alerts

    for alert_type, severity, message in alerts:
        Alert.objects.create(
            device_id=device_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
        )
        _publish_alert(device_id, alert_type, severity, message)

    _last_reading[device_id] = reading


def _publish_alert(device_id: str, alert_type: str, severity: str, message: str):
    global _mqtt_publish_client
    if _mqtt_publish_client is None:
        return
    payload = json.dumps({
        'device': device_id,
        'type': alert_type,
        'severity': severity,
        'message': message,
        'timestamp': timezone.now().isoformat(),
    })
    try:
        _mqtt_publish_client.publish(settings.MQTT_TOPIC_ALERT, payload)
    except Exception as e:
        logger.warning('Publish alert failed: %s', e)


_mqtt_publish_client = None


def publish_command(mode: str, azimuth: int = 90, elevation: int = 90):
    """Gửi lệnh điều khiển tới ESP qua MQTT."""
    global _mqtt_publish_client
    if _mqtt_publish_client is None:
        raise RuntimeError('MQTT bridge chưa chạy')

    if mode == 'auto':
        payload = '{"mode":"auto"}'
    else:
        payload = json.dumps({
            'mode': 'manual',
            'az': int(azimuth),
            'el': int(elevation),
        })

    _mqtt_publish_client.publish(
        settings.MQTT_TOPIC_COMMAND,
        payload,
        qos=1,
        retain=True,
    )
    return payload


def _on_telemetry(client, userdata, msg):
    data = _parse_json(msg.payload.decode('utf-8', errors='replace'))
    if not data:
        return

    device_id = data.get('device', 'solar_tracker_01')
    now = timezone.now()

    reading = SensorReading.objects.create(
        device_id=device_id,
        timestamp=now,
        ldr_tl=data.get('ldr_tl', 0),
        ldr_tr=data.get('ldr_tr', 0),
        ldr_bl=data.get('ldr_bl', 0),
        ldr_br=data.get('ldr_br', 0),
        light_total=data.get('light_total', 0),
        azimuth=data.get('azimuth', 0),
        elevation=data.get('elevation', 0),
        mode=data.get('mode', 'auto'),
        wifi_rssi=data.get('wifi_rssi'),
    )

    # Khong ghi de mode tu telemetry — mode chi doi khi web gui lenh (api/command)
    state, _ = SystemState.objects.get_or_create(
        device_id=device_id,
        defaults={'mode': 'auto'},
    )
    state.online = True
    state.last_seen = now
    state.azimuth = data.get('azimuth', 0)
    state.elevation = data.get('elevation', 0)
    state.light_total = data.get('light_total', 0)
    state.save(update_fields=[
        'online', 'last_seen', 'azimuth', 'elevation', 'light_total',
    ])

    _check_anomalies(device_id, data, reading)
    logger.debug('Telemetry saved: %s', device_id)


def _on_status(client, userdata, msg):
    data = _parse_json(msg.payload.decode('utf-8', errors='replace'))
    if not data:
        return
    device_id = data.get('device', 'solar_tracker_01')
    online = data.get('online', True)
    SystemState.objects.update_or_create(
        device_id=device_id,
        defaults={'online': online, 'last_seen': timezone.now()},
    )


def mark_offline_devices():
    """Đánh dấu thiết bị offline nếu không nhận tín hiệu."""
    threshold = timezone.now() - timedelta(seconds=settings.ALERT_OFFLINE_SECONDS)
    stale = SystemState.objects.filter(last_seen__lt=threshold, online=True)
    for state in stale:
        state.online = False
        state.save(update_fields=['online'])
        Alert.objects.create(
            device_id=state.device_id,
            alert_type='device_offline',
            severity='critical',
            message=f'Thiết bị {state.device_id} mất kết nối quá {settings.ALERT_OFFLINE_SECONDS}s',
        )


_bridge_thread = None
_bridge_running = False


def _offline_checker_loop():
    import time
    while _bridge_running:
        try:
            mark_offline_devices()
        except Exception as e:
            logger.exception('Offline checker error: %s', e)
        time.sleep(10)


def _broker_hint() -> str:
    host = settings.MQTT_BROKER_HOST
    port = settings.MQTT_BROKER_PORT
    return (
        f'Khong ket noi duoc MQTT broker tai {host}:{port}.\n'
        '  1) Cai Mosquitto: https://mosquitto.org/download/\n'
        '  2) Mo terminal ADMIN, chay: net start mosquitto\n'
        '     hoac: mosquitto -c server\\mosquitto\\mosquitto.conf -v\n'
        '  3) Chay lai: python manage.py run_mqtt_bridge\n'
        '     (bridge se tu thu lai moi 5 giay)'
    )


def start_mqtt_bridge(on_status=None):
    """Khoi dong MQTT client (goi tu management command)."""
    import time

    global _mqtt_publish_client, _bridge_thread, _bridge_running

    if _bridge_running:
        logger.info('MQTT bridge already running')
        return

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    def _on_connect(c, userdata, flags, reason_code, properties=None):
        logger.info('MQTT connected rc=%s', reason_code)
        c.subscribe(settings.MQTT_TOPIC_TELEMETRY)
        c.subscribe(settings.MQTT_TOPIC_STATUS)
        if on_status:
            on_status(True, f'Da ket noi {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}')

    client.on_connect = _on_connect

    def _message_router(c, userdata, msg):
        if msg.topic == settings.MQTT_TOPIC_TELEMETRY:
            _on_telemetry(c, userdata, msg)
        elif msg.topic == settings.MQTT_TOPIC_STATUS:
            _on_status(c, userdata, msg)

    client.on_message = _message_router

    retry = 0
    while True:
        try:
            client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60)
            break
        except (ConnectionRefusedError, OSError) as exc:
            retry += 1
            msg = _broker_hint()
            logger.warning('MQTT connect failed (%s): %s', exc, settings.MQTT_BROKER_HOST)
            if on_status:
                on_status(False, msg if retry == 1 else f'Cho broker... (lan thu {retry})')
            time.sleep(5)

    _mqtt_publish_client = client
    _bridge_running = True

    checker = threading.Thread(target=_offline_checker_loop, daemon=True)
    checker.start()

    client.loop_forever()
