/*
 * He thong theo doi nang luong mat troi - ESP8266 NodeMCU
 *
 * Chan:
 *   PCF8591: SDA=D2(GPIO4), SCL=D1(GPIO5)
 *   Servo ngang: D3 (GPIO0)
 *   Servo doc:   D4 (GPIO2)
 *   (Rain sensor removed)
 *
 * Thu vien: ESP8266 core, PubSubClient, Wire
 */

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>

const char* WIFI_SSID     = "6 anh em siu nhan";
const char* WIFI_PASSWORD = "mangnhaembihu";
const char* MQTT_SERVER   = "192.168.1.8";
const uint16_t MQTT_PORT  = 1883;
const char* MQTT_USER     = "";
const char* MQTT_PASS     = "";
const char* DEVICE_ID     = "solar_tracker_01";

const char* TOPIC_TELEMETRY = "solar/telemetry";
const char* TOPIC_STATUS    = "solar/status";
const char* TOPIC_COMMAND   = "solar/command";

#define PIN_SERVO_AZ    0    // D3 — servo ngang (GPIO0) - CHÚ Ý: GPIO0 ảnh hưởng chế độ nạp
#define PIN_SERVO_EL    2    // D4 — servo doc
// rain sensor removed
// Cam bien mua chi dung D7 (GPIO13)

#define PCF8591_ADDR    0x48 
#define LDR_EAST  0
#define LDR_WEST  1
#define LDR_NORTH 2
#define LDR_SOUTH 3

const int NGUONG_TOI       = 50;
const int GOC_NGHIENG_MUA  = 30;
const int TOC_DO_QUAY      = 25;   // ms/buoc (80=cham). Nho hon = quay nhanh, de thay khi demo
const int BUOC_GOC_DEMO    = 3;    // so do moi lan nhay (1=muot, 3=nhanh cho demo)
const int GOC_MIN          = 0;
const int GOC_MAX          = 180;

// Các góc cơ bản để xử lý khi mặt trời mọc/khuất không hoàn toàn hướng Đông
const int ANGLE_EAST       = 90;   // Đông (mặc định)
const int ANGLE_NE         = 60;   // Đông-Bắc (NE)
const int ANGLE_SE         = 120;  // Đông-Nam (SE)
const int NIGHT_TILT       = 0;    // Góc nghiêng ban đêm (reset)
const int MID_TILT         = 90;   // Góc nghiêng trung tính ban ngày
const int HYST             = 8;    // Độ chết (hysteresis) để phân biệt NE vs SE
const int TILT_MAX_DELTA   = 45;   // Độ lệch tối đa của góc nghiêng so với MID_TILT

// Ổn định / làm mịn tín hiệu
const float EMA_ALPHA      = 0.25;  // hệ số EMA (0-1) để làm mịn giá trị cảm biến
float emaLdr[4] = { -1.0, -1.0, -1.0, -1.0 };
const int MIN_MOVE_STEP    = 3;     // số độ tối thiểu để servo bắt đầu di chuyển
int lastComputedBase       = ANGLE_EAST;
int stableBaseCount        = 0;
const int STABLE_REQUIRED  = 3;

const unsigned long WIFI_TIMEOUT_MS = 25000;

WiFiClient espClient;
PubSubClient mqtt(espClient);

int gocAzimuth   = 90;
int gocElevation = 90;
bool cheDoTuDong = true;
bool wifiOK = false;
bool servoSanSang = false;

int gocAzManual = 90;
int gocElManual = 90;

unsigned long thoiGianBuocAz = 0;
unsigned long thoiGianBuocEl = 0;
unsigned long thoiGianGuiMQTT  = 0;
unsigned long thoiGianReconnect = 0;
unsigned long thoiGianHeartbeat = 0;
unsigned long thoiGianWifiRetry = 0;

const unsigned long INTERVAL_TELEMETRY = 2000;
const unsigned long INTERVAL_RECONNECT = 5000;
const unsigned long INTERVAL_HEARTBEAT = 3000;

// rain sensor removed

void yeildWatchdog() {
  yield();
  ESP.wdtFeed();
}

int docLDR(byte channel) {
  Wire.beginTransmission(PCF8591_ADDR);
  Wire.write(0x40 | (channel & 0x03));
  if (Wire.endTransmission() != 0) return -1;

  Wire.requestFrom((int)PCF8591_ADDR, 2);
  if (Wire.available() < 2) return -1;

  Wire.read();              // bỏ byte cũ
  int val = Wire.read();    // byte thật

  return val;
}

void guiXungServo(int pin, int goc) {
  if (!servoSanSang) return;
  goc = constrain(goc, GOC_MIN, GOC_MAX);
  int pulse = map(goc, 0, 180, 500, 2400);
  digitalWrite(pin, HIGH);
  delayMicroseconds(pulse);
  digitalWrite(pin, LOW);
  delayMicroseconds(20000 - pulse);
  yeildWatchdog();
}

void khoiTaoServo(int pin, int goc) {
  pinMode(pin, OUTPUT);
  for (int i = 0; i < 5; i++) {
    guiXungServo(pin, goc);
    delay(15);
    yeildWatchdog();
  }
}

// rain sensor removed: stub
bool docCamBienMua() {
  return false;
}

void tinhGocTuLDR(int& targetAz, int& targetEl, int e, int w, int n, int s) {
  int total = e + w + n + s;
  if (total < NGUONG_TOI) {
    // Ban đêm: đặt về Đông và góc nghiêng bằng 0
    targetAz = ANGLE_EAST;
    targetEl = NIGHT_TILT;
    return;
  }

  // Logic góc đế (azimuth) theo yêu cầu:
  // - Chia thành 2 cụm: SE = East + South (map 0..90, 0=Nam,90=Đông)
  //                  NE = East + North (map 90..180, 90=Đông,180=Bắc)
  // - So sánh tổng hai cụm; cụm mạnh hơn sẽ được dùng để map góc.
  // - Nếu chênh lệch tương đối nhỏ thì giữ nguyên góc hiện tại (tránh chớp chớp).
  // - Nếu East quá lớn còn North và South quá nhỏ thì đặt thẳng về Đông (90°).
  int clusterSE = e + s;
  int clusterNE = e + n;

  // If both clusters too small, fallback to east
  if (clusterSE < NGUONG_TOI && clusterNE < NGUONG_TOI) {
    targetAz = ANGLE_EAST;
  } else {
    // Nếu tổng hai cụm không chênh lệch đáng kể thì giữ nguyên (tránh rung)
    int sumClusters = clusterSE + clusterNE;
    float relDiff = (sumClusters > 0) ? (float)abs(clusterSE - clusterNE) / (float)sumClusters : 0.0f;
    const float REL_DIFF_THRESHOLD = 0.15f; // ngưỡng chênh lệch tương đối 15% để chuyển cụm

    if (relDiff < REL_DIFF_THRESHOLD) {
      // giữ nguyên targetAz (không thay đổi)
    } else {
      if (clusterSE > clusterNE) {
        // Map trong khoảng 0..90 theo tỉ lệ East vs South
        if (clusterSE > 0) {
          float pEast = (float)e / (float)clusterSE; // 0..1 (0=>toàn Nam,1=>toàn Đông)
          int ang = constrain((int)(pEast * 90.0f + 0.5f), 0, 90);
          targetAz = ang; // 0..90
        }
      } else {
        // Nếu cụm NE mạnh -> map 90..180 theo tỉ lệ North vs East
        if (clusterNE > 0) {
          float pNorth = (float)n / (float)clusterNE; // 0..1 (0=>toàn Đông,1=>toàn Bắc)
          int ang = 90 + constrain((int)(pNorth * 90.0f + 0.5f), 0, 90);
          targetAz = ang; // 90..180
        }
      }

      // Trường hợp đặc biệt: East quá lớn, North và South nhỏ -> đặt về Đông
      if (e > (n + s) * 3 && n < NGUONG_TOI && s < NGUONG_TOI) {
        targetAz = ANGLE_EAST;
      }
    }
  }

  // Logic góc nghiêng (elevation):
  // - Dùng cảm biến Đông và Tây: targetEl = (East/(East+West)) * 180
  // - Nếu tổng East+West quá nhỏ thì giữ nguyên góc (không thay đổi)
  int sumEW = e + w;
  if (sumEW > 0 && sumEW >= NGUONG_TOI) {
    float tiLe = (float)e / (float)sumEW; // 0..1
    int elAng = constrain((int)(tiLe * 180.0f + 0.5f), GOC_MIN, GOC_MAX);
    targetEl = elAng;
  } else {
    // giữ nguyên targetEl (caller sẽ dùng giá trị trước đó)
  }
}

void buocGoc(int& hienTai, int mucTieu, unsigned long& thoiGianBuoc) {
  if (millis() - thoiGianBuoc < (unsigned long)TOC_DO_QUAY) return;
  if (abs(hienTai - mucTieu) < MIN_MOVE_STEP) return; // vùng chết để tránh rung/nhảy servo
  int buoc = BUOC_GOC_DEMO;
  if (hienTai < mucTieu) {
    hienTai = min(hienTai + buoc, mucTieu);
  } else if (hienTai > mucTieu) {
    hienTai = max(hienTai - buoc, mucTieu);
  }
  thoiGianBuoc = millis();
}

void apDungLogicMua(int& targetAz, int& targetEl, int tongAnhSang) {
  // rain logic removed
  (void)targetAz; (void)targetEl; (void)tongAnhSang;
}

int parseJsonInt(const String& msg, const char* key) {
  String needle = String("\"") + key + "\":";
  int idx = msg.indexOf(needle);
  if (idx < 0) return -1;
  return msg.substring(idx + needle.length()).toInt();
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  msg.trim();

  Serial.print(F("Lenh MQTT: "));
  Serial.println(msg);

  if (msg.startsWith("manual,")) {
    cheDoTuDong = false;
    int p1 = msg.indexOf(',');
    int p2 = msg.indexOf(',', p1 + 1);
    if (p1 > 0 && p2 > p1) {
      gocAzManual = constrain(msg.substring(p1 + 1, p2).toInt(), GOC_MIN, GOC_MAX);
      gocElManual = constrain(msg.substring(p2 + 1).toInt(), GOC_MIN, GOC_MAX);
    }
  } else if (msg.indexOf("\"manual\"") >= 0 || msg.indexOf("manual") >= 0) {
    cheDoTuDong = false;
    int az = parseJsonInt(msg, "az");
    int el = parseJsonInt(msg, "el");
    if (az >= 0) gocAzManual = constrain(az, GOC_MIN, GOC_MAX);
    if (el >= 0) gocElManual = constrain(el, GOC_MIN, GOC_MAX);
  } else if (msg.indexOf("\"auto\"") >= 0 || msg == "auto") {
    cheDoTuDong = true;
    Serial.println(F("Che do: TU DONG"));
    return;
  } else {
    return;
  }

  // ĐÃ SỬA LỖI Ở ĐÂY: Bỏ macro F() để tương thích với Serial.printf
  Serial.printf("Che do: THU CONG -> Az:%d El:%d\n", gocAzManual, gocElManual);
}

void inLoiMQTT(int state) {
  Serial.print(F("MQTT loi "));
  Serial.println(state);
}

void connectMQTT() {
  if (mqtt.connected() || !wifiOK) return;
  String clientId = String(DEVICE_ID) + "_" + String(random(0xffff), HEX);
  mqtt.setKeepAlive(60);
  mqtt.setSocketTimeout(10);
  bool ok = (strlen(MQTT_USER) > 0)
    ? mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)
    : mqtt.connect(clientId.c_str());
  if (ok) {
    mqtt.subscribe(TOPIC_COMMAND);
    Serial.println(F(">>> MQTT OK <<<"));
    String status = "{\"device\":\"" + String(DEVICE_ID) + "\",\"online\":true}";
    mqtt.publish(TOPIC_STATUS, status.c_str(), true);
  } else {
    inLoiMQTT(mqtt.state());
  }
}

void guiTelemetry(int tl, int tr, int bl, int br, int tong) {
  String payload = "{";
  payload += "\"device\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"ldr_tl\":" + String(tl) + ",";
  payload += "\"ldr_tr\":" + String(tr) + ",";
  payload += "\"ldr_bl\":" + String(bl) + ",";
  payload += "\"ldr_br\":" + String(br) + ",";
  payload += "\"light_total\":" + String(tong) + ",";
  payload += "\"azimuth\":" + String(gocAzimuth) + ",";
  payload += "\"elevation\":" + String(gocElevation) + ",";
  payload += "\"mode\":\"" + String(cheDoTuDong ? "auto" : "manual") + "\",";
  payload += "\"wifi_rssi\":" + String(WiFi.RSSI());
  payload += "}";
  mqtt.publish(TOPIC_TELEMETRY, payload.c_str());
}

void inLoiWiFi(uint8_t st) {
  Serial.print(F("WiFi that bai, ma "));
  Serial.print(st);
  Serial.print(F(": "));
  switch (st) {
    case WL_NO_SSID_AVAIL: Serial.println(F("Khong tim thay WiFi - sai ten mang (SSID)")); break;
    case WL_CONNECT_FAILED: Serial.println(F("Ket noi that bai - sai mat khau hoac WiFi 5GHz")); break;
    case WL_CONNECTION_LOST: Serial.println(F("Mat ket noi")); break;
    case WL_DISCONNECTED: Serial.println(F("Chua ket noi")); break;
    default: Serial.println(F("Loi khac - ESP chi dung WiFi 2.4GHz")); break;
  }
}

bool ketNoiWiFi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  delay(100);
  WiFi.mode(WIFI_STA);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFi.disconnect(true);
  delay(200);

  Serial.print(F("Dang ket noi WiFi: "));
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  int soCham = 0;
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) {
    delay(400);
    if (soCham < 40) {
      Serial.print('.');
      soCham++;
    }
    yeildWatchdog();
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    wifiOK = true;
    Serial.print(F("WiFi OK! IP ESP: "));
    Serial.println(WiFi.localIP());
    return true;
  }

  inLoiWiFi(WiFi.status());
  Serial.println(F("Van chay servo + LDR. Sua SSID/mat khau roi nap lai."));
  wifiOK = false;
  return false;
}

void setup() {
  // rain sensor removed

  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println(F("========================================"));
  Serial.println(F("  SOLAR TRACKER - FIRMWARE MOI v2"));
  Serial.println(F("  (Neu thay 'Hay truy cap IP' = code CU)"));
  Serial.println(F("========================================"));

  Wire.begin(4, 5);
  Wire.setClock(100000);

  // Ket noi WiFi TRUOC khi quay servo (giam reset nguon)
  ketNoiWiFi();

  ESP.wdtEnable(15000);
  servoSanSang = true;
  khoiTaoServo(PIN_SERVO_AZ, gocAzimuth);
  khoiTaoServo(PIN_SERVO_EL, gocElevation);
  Serial.println(F("Servo san sang (ngang=D5, doc=D4)"));

  Serial.println(F("Test servo doc 70-110-90..."));
  for (int g = 70; g <= 110; g += 10) {
    guiXungServo(PIN_SERVO_EL, g);
    delay(200);
    yeildWatchdog();
  }
  guiXungServo(PIN_SERVO_EL, 90);
  gocElevation = 90;
  Serial.println(F("Test servo doc xong"));

  if (wifiOK) {
    mqtt.setServer(MQTT_SERVER, MQTT_PORT);
    mqtt.setCallback(mqttCallback);
    mqtt.setBufferSize(512);
    connectMQTT();
  }

  Serial.print(F("MQTT server: "));
  Serial.println(MQTT_SERVER);
  Serial.println(F("He thong dang chay..."));
}

void loop() {
  yeildWatchdog();
  if (WiFi.status() != WL_CONNECTED) {
    wifiOK = false;
    if (millis() - thoiGianWifiRetry > 20000) {
      Serial.println(F("Thu ket noi WiFi lai..."));
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      thoiGianWifiRetry = millis();
    }
  } else {
    wifiOK = true;
    if (!mqtt.connected() && millis() - thoiGianReconnect >= INTERVAL_RECONNECT) {
      connectMQTT();
      thoiGianReconnect = millis();
    } else if (mqtt.connected()) {
      mqtt.loop();
    }
  }

  int e_raw = docLDR(LDR_EAST);
  int w_raw = docLDR(LDR_WEST);
  int n_raw = docLDR(LDR_NORTH);
  int s_raw = docLDR(LDR_SOUTH);

  int raws[4] = {e_raw, w_raw, n_raw, s_raw};
  for (int i = 0; i < 4; i++) {
    if (emaLdr[i] < 0) emaLdr[i] = raws[i];
    else emaLdr[i] = EMA_ALPHA * raws[i] + (1.0 - EMA_ALPHA) * emaLdr[i];
  }

  int e = (int)emaLdr[0];
  int w = (int)emaLdr[1];
  int n = (int)emaLdr[2];
  int s = (int)emaLdr[3];

  int tongAnhSang = e + w + n + s;
  int targetAz = gocAzimuth;
  int targetEl = gocElevation;

  if (cheDoTuDong) {
    int proposedAz = gocAzimuth;
    int proposedEl = gocElevation;
    tinhGocTuLDR(proposedAz, proposedEl, e, w, n, s);

    if (proposedAz == lastComputedBase) {
      stableBaseCount++;
    } else {
      lastComputedBase = proposedAz;
      stableBaseCount = 1;
    }

    if (stableBaseCount >= STABLE_REQUIRED) {
      targetAz = proposedAz;
    } else {
      targetAz = gocAzimuth; // wait until stable
    }

    targetEl = proposedEl;

    apDungLogicMua(targetAz, targetEl, tongAnhSang);
    buocGoc(gocAzimuth, targetAz, thoiGianBuocAz);
    buocGoc(gocElevation, targetEl, thoiGianBuocEl);
  } else {
    buocGoc(gocAzimuth, constrain(gocAzManual, GOC_MIN, GOC_MAX), thoiGianBuocAz);
    /* If enabling rain lock, use:
    if (!rainLocked) {
      buocGoc(gocElevation, constrain(gocElManual, GOC_MIN, GOC_MAX), thoiGianBuocEl);
    }
    */
    buocGoc(gocElevation, constrain(gocElManual, GOC_MIN, GOC_MAX), thoiGianBuocEl);
  }

  gocAzimuth   = constrain(gocAzimuth, GOC_MIN, GOC_MAX);
  gocElevation = constrain(gocElevation, GOC_MIN, GOC_MAX);

  guiXungServo(PIN_SERVO_AZ, gocAzimuth);
  guiXungServo(PIN_SERVO_EL, gocElevation);

  if (millis() - thoiGianGuiMQTT >= INTERVAL_TELEMETRY) {
    if (mqtt.connected()) {
      guiTelemetry(e, w, n, s, tongAnhSang);
    }
    thoiGianGuiMQTT = millis();
  }

  if (millis() - thoiGianHeartbeat >= INTERVAL_HEARTBEAT) {
    Serial.printf("Song | WiFi:%s MQTT:%s | E:%d W:%d N:%d S:%d Az:%d El:%d\n",
      wifiOK ? "OK" : "NO",
      mqtt.connected() ? "OK" : "NO",
      e, w, n, s, gocAzimuth, gocElevation);
    thoiGianHeartbeat = millis();
  } 
} 