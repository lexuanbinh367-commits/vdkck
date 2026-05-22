/**
 * Dashboard giám sát năng lượng mặt trời
 */
const POLL_MS = 2000;
const HISTORY_LIMIT = 80;
const DEVICE_ID = 'solar_tracker_01';
const SLIDER_DEBOUNCE_MS = 150;

let isOnline = false;
let currentMode = 'auto';
let chartLight = null;
let chartAngles = null;
let sliderDebounceTimer = null;
let userEditingSliders = false;

const $ = (id) => document.getElementById(id);

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function setConnectionUI(online, lastSeen) {
  isOnline = online;
  const dot = $('statusDot');
  const text = $('statusText');
  const badge = $('dataSource');

  dot.className = 'status-dot ' + (online ? 'online' : 'offline');
  text.textContent = online ? 'Đã kết nối hệ thống' : 'Mất kết nối với ESP';
  $('lastSeen').textContent = lastSeen ? `Cập nhật: ${formatTime(lastSeen)}` : '';

  badge.textContent = online ? 'Trực tiếp' : 'Ngoại tuyến';
  badge.classList.toggle('offline', !online);
}

function updateStats(reading, status) {
  if (reading) {
    $('lightTotal').textContent = reading.light_total;
    $('anglesNow').textContent = `${reading.azimuth}° / ${reading.elevation}°`;
  }
  if (status && currentMode === 'manual') {
    $('anglesNow').textContent =
      `${status.azimuth}° / ${status.elevation}° (đặt: ${status.target_azimuth}° / ${status.target_elevation}°)`;
  }
}

function appendLogRow(r) {
  const tbody = $('logBody');
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${formatTime(r.timestamp)}</td>
    <td>${r.ldr_east}</td>
    <td>${r.ldr_west}</td>
    <td>${r.ldr_north}</td>
    <td>${r.ldr_south}</td>
    <td>${r.light_total}</td>
    <td>${r.azimuth}</td>
    <td>${r.elevation}</td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
  while (tbody.children.length > 50) tbody.removeChild(tbody.lastChild);
}

function renderAlerts(alerts) {
  const el = $('alertsList');
  if (!alerts || !alerts.length) {
    el.innerHTML = '<p style="color:var(--muted);font-size:0.8rem">Không có cảnh báo</p>';
    return;
  }
  const critical = alerts.find((a) => a.severity === 'critical' && !a.acknowledged);
  const banner = $('alertBanner');
  if (critical) {
    banner.textContent = '⚠ ' + critical.message;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
  el.innerHTML = alerts
    .slice(0, 8)
    .map(
      (a) => `
    <div class="alert-item ${a.severity}">
      ${a.message}
      <time>${formatTime(a.timestamp)}</time>
    </div>`
    )
    .join('');
}

function initCharts() {
  const common = {
    responsive: false,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    plugins: { legend: { labels: { color: '#8b9cb3' } } },
    scales: {
      x: {
        ticks: { color: '#8b9cb3', maxTicksLimit: 8 },
        grid: { color: 'rgba(42,53,72,0.6)' },
      },
      y: {
        ticks: { color: '#8b9cb3' },
        grid: { color: 'rgba(42,53,72,0.6)' },
      },
    },
  };

  chartLight = new Chart($('chartLight'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'Đông', data: [], borderColor: '#f97316', tension: 0.3 },
        { label: 'Tây', data: [], borderColor: '#ef4444', tension: 0.3 },
        { label: 'Bắc', data: [], borderColor: '#3b82f6', tension: 0.3 },
        { label: 'Nam', data: [], borderColor: '#10b981', tension: 0.3 },
      ],
    },
    options: common,
  });

  chartAngles = new Chart($('chartAngles'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'Góc ngang (°)', data: [], borderColor: '#22c55e', tension: 0.3 },
        { label: 'Góc dọc (°)', data: [], borderColor: '#3b82f6', tension: 0.3 },
      ],
    },
    options: common,
  });
}

function updateCharts(readings) {
  if (!readings.length) return;
  const labels = readings.map((r) => formatTime(r.timestamp));
  chartLight.data.labels = labels;
  chartLight.data.datasets[0].data = readings.map((r) => r.ldr_east);
  chartLight.data.datasets[1].data = readings.map((r) => r.ldr_west);
  chartLight.data.datasets[2].data = readings.map((r) => r.ldr_north);
  chartLight.data.datasets[3].data = readings.map((r) => r.ldr_south);
  chartLight.update('none');
  chartAngles.data.labels = labels;
  chartAngles.data.datasets[0].data = readings.map((r) => r.azimuth);
  chartAngles.data.datasets[1].data = readings.map((r) => r.elevation);
  chartAngles.update('none');
}

function applyModeUI(mode) {
  currentMode = mode;
  if (mode === 'manual') {
    $('btnManual').classList.add('active');
    $('btnAuto').classList.remove('active');
    $('manualControls').classList.remove('hidden');
  } else {
    $('btnAuto').classList.add('active');
    $('btnManual').classList.remove('active');
    $('manualControls').classList.add('hidden');
    userEditingSliders = false;
  }
}

function setSliders(az, el) {
  $('sliderAz').value = az;
  $('sliderEl').value = el;
  $('azVal').textContent = az;
  $('elVal').textContent = el;
}

async function sendCommand(mode, azimuth = 90, elevation = 90) {
  try {
    const data = await fetchJSON('/api/command/', {
      method: 'POST',
      body: JSON.stringify({
        device: DEVICE_ID,
        mode,
        azimuth,
        elevation,
      }),
    });
    if (data.mqtt_sent) {
      $('btnApplyManual').textContent = 'Đã gửi lệnh ✓';
      setTimeout(() => { $('btnApplyManual').textContent = 'Áp dụng góc'; }, 1500);
    } else if (data.warning) {
      console.warn('Chưa gửi MQTT:', data.warning);
      $('btnApplyManual').textContent = 'Đã lưu (ESP offline)';
      setTimeout(() => { $('btnApplyManual').textContent = 'Áp dụng góc'; }, 2000);
    }
    return data;
  } catch (e) {
    console.error('Gửi lệnh thất bại:', e);
    alert('Không gửi được lệnh. Kiểm tra server và MQTT bridge.');
    return null;
  }
}

function sendManualFromSliders() {
  const az = parseInt($('sliderAz').value, 10);
  const el = parseInt($('sliderEl').value, 10);
  return sendCommand('manual', az, el);
}

function scheduleManualSend() {
  if (currentMode !== 'manual') return;
  clearTimeout(sliderDebounceTimer);
  sliderDebounceTimer = setTimeout(() => {
    sendManualFromSliders();
    userEditingSliders = false;
  }, SLIDER_DEBOUNCE_MS);
}

function setupControls() {
  $('btnAuto').addEventListener('click', async () => {
    applyModeUI('auto');
    await sendCommand('auto');
  });

  $('btnManual').addEventListener('click', async () => {
    applyModeUI('manual');
    // Gửi lệnh manual với góc hiện tại thay vì góc slider (luôn 90)
    const status = await fetchJSON(`/api/status/?device=${DEVICE_ID}`);
    if (status) {
      const az = status.azimuth ?? 90;
      const el = status.elevation ?? 90;
      setSliders(az, el);
      sendCommand('manual', az, el);
    }
  });

  const sliderAz = $('sliderAz');
  const sliderEl = $('sliderEl');

  const onSliderInput = () => {
    $('azVal').textContent = sliderAz.value;
    $('elVal').textContent = sliderEl.value;
    if (currentMode === 'manual') {
      userEditingSliders = true;
      scheduleManualSend();
    }
  };

  sliderAz.addEventListener('input', onSliderInput);
  sliderEl.addEventListener('input', onSliderInput);
  sliderAz.addEventListener('mousedown', () => { userEditingSliders = true; });
  sliderEl.addEventListener('mousedown', () => { userEditingSliders = true; });

  $('btnApplyManual').addEventListener('click', () => {
    userEditingSliders = false;
    sendManualFromSliders();
  });
}

async function poll() {
  try {
    const [status, latest, history, alerts] = await Promise.all([
      fetchJSON(`/api/status/?device=${DEVICE_ID}`),
      fetchJSON(`/api/latest/?device=${DEVICE_ID}`),
      fetchJSON(`/api/history/?device=${DEVICE_ID}&limit=${HISTORY_LIMIT}`),
      fetchJSON(`/api/alerts/?device=${DEVICE_ID}&limit=10`),
    ]);

    setConnectionUI(status.online, status.last_seen);

    if (status.mode === 'manual') {
      applyModeUI('manual');
    } else if (currentMode !== 'manual') {
      applyModeUI('auto');
    }

    // Thanh keo: dung goc DAT (target), khong bi telemetry ghi de
    if (!userEditingSliders) {
      if (status.mode === 'manual') {
        setSliders(status.target_azimuth ?? 90, status.target_elevation ?? 90);
      } else if (status.azimuth != null) {
        setSliders(status.azimuth, status.elevation);
      }
    }

    const reading = latest.reading || (history.readings.length ? history.readings[history.readings.length - 1] : null);
    if (reading) {
      updateStats(reading, status);
      if (isOnline) appendLogRow(reading);
    }

    if (history.readings.length) {
      updateCharts(history.readings);
      if (!isOnline && $('logBody').children.length === 0) {
        history.readings.slice().reverse().forEach((r) => appendLogRow(r));
      }
    }

    renderAlerts(alerts.alerts);
  } catch (e) {
    console.error('Poll error:', e);
    setConnectionUI(false, null);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  setupControls();
  poll();
  setInterval(poll, POLL_MS);
});
