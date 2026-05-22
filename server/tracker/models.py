from django.db import models
from django.utils import timezone


class SensorReading(models.Model):
    """Bản ghi cường độ ánh sáng và góc servo."""

    device_id = models.CharField(max_length=64, default='solar_tracker_01', db_index=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    ldr_tl = models.IntegerField(default=0)
    ldr_tr = models.IntegerField(default=0)
    ldr_bl = models.IntegerField(default=0)
    ldr_br = models.IntegerField(default=0)
    light_total = models.IntegerField(default=0)

    azimuth = models.IntegerField(default=0)
    elevation = models.IntegerField(default=0)

    rain = models.BooleanField(default=False)
    mode = models.CharField(max_length=16, default='auto')
    wifi_rssi = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['device_id', '-timestamp']),
        ]

    def __str__(self):
        return f'{self.device_id} @ {self.timestamp:%H:%M:%S}'


class SystemState(models.Model):
    """Trạng thái hiện tại của thiết bị (1 bản ghi / device)."""

    device_id = models.CharField(max_length=64, unique=True)
    online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)

    mode = models.CharField(max_length=16, default='auto')
    azimuth = models.IntegerField(default=90)       # goc thuc te tu ESP
    elevation = models.IntegerField(default=90)
    target_azimuth = models.IntegerField(default=90)   # goc dat tu web (thu cong)
    target_elevation = models.IntegerField(default=90)

    light_total = models.IntegerField(default=0)
    rain = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Trạng thái hệ thống'
        verbose_name_plural = 'Trạng thái hệ thống'

    def __str__(self):
        status = 'Online' if self.online else 'Offline'
        return f'{self.device_id} ({status})'


class Alert(models.Model):
    """Cảnh báo dữ liệu bất thường."""

    SEVERITY_CHOICES = [
        ('info', 'Thông tin'),
        ('warning', 'Cảnh báo'),
        ('critical', 'Nghiêm trọng'),
    ]

    device_id = models.CharField(max_length=64, default='solar_tracker_01', db_index=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='warning')
    alert_type = models.CharField(max_length=64)
    message = models.TextField()
    acknowledged = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.severity}] {self.alert_type}: {self.message[:50]}'
