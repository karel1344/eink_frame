# E-Ink Photo Frame

Raspberry Pi Zero 2 W + Waveshare Spectra 6 E-Ink 디지털 액자

## 동작 흐름

```
06:00 AM
    │
    ▼
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  Boot   │────▶│  Sync   │────▶│ Display │────▶│Shutdown │
└─────────┘     └─────────┘     └─────────┘     └─────────┘
                                                     │
                                              24시간 대기 (~10μA)
```

## 하드웨어

| 구성품 | 모델 |
|--------|------|
| 메인보드 | Raspberry Pi Zero 2 W |
| 디스플레이 | Waveshare 7.3" Spectra 6 (800x480, 6색) |
| 전원관리 | Witty Pi 4 L3V7 |
| 배터리 | 리튬이온 3.7V |

```
Pi Zero 2 W
├── SPI0 ─────── E-Ink Display
├── I2C1 ─────── Witty Pi 4
└── GPIO17 ───── Button
```

## 설치 (Pi)

```bash
# 의존성 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install RPi.GPIO spidev smbus2 gpiozero

# NetworkManager 권한 설정 (polkit)
sudo nano /etc/polkit-1/rules.d/10-network-manager.rules
```

polkit 내용:
```javascript
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 &&
        subject.user == "myungs") {
        return polkit.Result.YES;
    }
});
```

```bash
sudo systemctl restart polkit

# 서비스 등록 (부팅 시 자동 실행)
sudo ./scripts/install_service.sh
```

## 실행

```bash
# 개발 모드 (Mac, WiFi 연결 시도 안함)
python einkframe.py --dev
# http://localhost:8000

# 프로덕션 모드 (Pi, WiFi 연결 → 실패 시 AP 모드)
sudo python einkframe.py

# 서비스로 실행
sudo systemctl start einkframe
sudo journalctl -u einkframe -f  # 로그 확인
```

## 상태머신

```
INIT ──▶ WIFI_CONNECT ──▶ PHOTO_UPDATE ──▶ SCHEDULE ──▶ SHUTDOWN
              │
       버튼/실패/에러
              ▼
           AP_MODE (웹 UI)
```

## 디렉토리

```
eink_frame/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── display/
│   ├── photo_source/
│   ├── web/
│   └── wifi/
├── config/settings.yaml
├── photos/local/
├── photos/google/
└── docs/SPEC.md
```

## 설정 (config/settings.yaml)

```yaml
schedule:
  update_time: "06:00"

wifi:
  enabled: true
  ssid: ""
  password: ""

photo_selection:
  mode: "random"  # random / sequential / date_based

photo_sources:
  local:
    enabled: true
  google_photos:
    enabled: false
    album_id: ""
```

## API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/status` | 시스템 상태 |
| GET | `/api/settings` | 설정 조회 |
| PUT | `/api/settings` | 설정 변경 |
| GET | `/api/wifi/scan` | WiFi 스캔 |
| GET | `/api/wifi/status` | WiFi 상태 |
| POST | `/api/wifi/connect` | WiFi 연결 |
| GET | `/api/ap/status` | AP 모드 상태 |
| POST | `/api/ap/start` | AP 모드 시작 |
| POST | `/api/ap/stop` | AP 모드 종료 |
| GET | `/api/photos` | 사진 목록 |
| POST | `/api/photos/upload` | 사진 업로드 |
| POST | `/api/system/apply` | 적용 후 재연결 |
| POST | `/api/system/shutdown` | 종료 |

## 웹 UI 모드 진입

- 버튼 누름 (WiFi 연결 중)
- WiFi 연결 실패
- 에러 발생

AP 이름: `EinkFrame-XXXX`

## 전력 소비

| 상태 | 소비 전력 |
|------|----------|
| 종료 (Witty Pi 대기) | ~10μA |
| 부팅 + WiFi | ~200-400mA |
| E-Ink 새로고침 | ~50-100mA |

## 트러블슈팅

```bash
# WiFi 스캔 안됨
sudo apt install network-manager
nmcli device wifi list

# AP 모드 권한 오류 (Not authorized to control networking)
sudo nano /etc/polkit-1/rules.d/10-network-manager.rules
# 위의 polkit 설정 추가 후
sudo systemctl restart polkit

# AP 모드 수동 종료
nmcli connection down Hotspot
nmcli connection down EinkFrame-Open

# 서비스 상태 확인
sudo systemctl status einkframe
sudo journalctl -u einkframe -f

# SPI 활성화
sudo raspi-config  # Interface Options > SPI > Enable

# 포트 열기
sudo ufw allow 80
sudo ufw allow 8000
```
