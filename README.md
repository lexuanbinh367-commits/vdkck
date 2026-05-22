# Năng lượng mặt trời thông minh

## Chạy hệ thống (chỉ 1 bước)

1. Mở **PowerShell (Quản trị viên)** — chuột phải PowerShell → **Run as administrator**
2. Chạy:

```powershell
cd D:\vdkck
.\CHAY.bat
```

*(Đổi `D:\vdkck` nếu bạn đặt project ở thư mục khác.)*

Giữ 2 cửa sổ mở:
1. **MQTT** — broker cho ESP
2. **Solar Web** — dashboard http://127.0.0.1:8000/

**Dừng:** PowerShell (Admin) → `cd D:\vdkck` → `.\STOP.bat`

---

## Cài lần đầu

1. Cài [MySQL](https://dev.mysql.com/downloads/installer/) (hoặc MariaDB) và tạo database:
   ```sql
   CREATE DATABASE solar_tracker CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
   Hoặc chạy file `server/scripts/create_mysql_db.sql`.

2. Cài [Mosquitto](https://mosquitto.org/download/)

3. Trong `server`:
   ```cmd
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   copy .env.example .env
   ```
   Sửa `.env` (user, password MySQL), rồi:
   ```cmd
   venv\Scripts\python manage.py migrate
   ```

4. Sửa WiFi + IP máy tính trong `firmware/solar_tracker_esp8266/solar_tracker_esp8266.ino`:
   - `MQTT_SERVER` = IP PC (lệnh `ipconfig`)
5. Nạp code ESP (Arduino IDE, 115200 baud)

---

## ESP phải hiện

```
WiFi OK! IP ESP: 192.168.1.xx
>>> MQTT OK <<<
```

Nếu `MQTT loi -2`: mở lại PowerShell (Admin) và chạy lại `.\CHAY.bat` (không dùng `net start mosquitto`).

---

## Phần cứng

| Thành phần | Chân ESP |
|------------|----------|
| PCF8591 I2C | D1 SCL, D2 SDA |
| Servo ngang (signal) | D5 |
| Servo dọc (signal) | D4 |
| Mưa (DO) | D3 |
