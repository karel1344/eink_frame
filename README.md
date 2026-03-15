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
└── GPIO27 ───── Button
```

## 설치 (Pi)

```bash
# 자동 설치 (venv, 의존성, systemd 서비스, polkit 등)
sudo ./scripts/install_service.sh
```

수동 설치가 필요한 경우:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 실행

```bash
# 개발 모드 (Mac, 웹 UI만 실행)
python einkframe.py --dev
# http://localhost:8000

# 프로덕션 모드 (Pi, 상태머신 전체 실행)
sudo python einkframe.py

# 사진 표시만 실행 (1회)
python einkframe.py --frame

# 디버그 모드 (debug_output.png로 저장, Mac 테스트)
python einkframe.py --frame --dry-run

# 서비스로 실행
sudo systemctl start einkframe
sudo journalctl -u einkframe -f  # 로그 확인
```

## 상태머신

```
INIT ──▶ WIFI_CONNECT ──▶ PHOTO_UPDATE ──▶ SCHEDULE ──▶ SHUTDOWN
              │                                            │
       버튼/실패/에러                                  Witty Pi 알람 설정
              ▼
         WEB_UI_MODE ◀──▶ AP_MODE (웹 UI)
```

- 버튼: GPIO27 (부팅 시 눌려있으면 WEB_UI_MODE 진입)
- AP 이름: `EinkFrame-XXXX`

## 디렉토리

```
eink_frame/
├── einkframe.py          # CLI 진입점
├── config/settings.yaml  # 사용자 설정
├── data/einkframe.db     # SQLite DB
├── src/
│   ├── main.py           # 레거시 진입점
│   ├── config.py         # YAML 설정 관리
│   ├── database.py       # SQLite (WAL 모드)
│   ├── state_machine.py  # 상태머신
│   ├── frame_runner.py   # 사진 표시 실행
│   ├── photo_selector.py # 사진 선택 로직
│   ├── image_processor.py # 이미지 처리 파이프라인
│   ├── power_manager.py  # Witty Pi I2C 연동
│   ├── startup.py        # 시작 시퀀스
│   ├── button.py         # GPIO 버튼 핸들러
│   ├── status_display.py # E-Ink 상태 화면
│   ├── display/          # E-Ink 드라이버 (7.3", 13.3")
│   ├── photo_source/     # 사진 소스 (local, google_photos)
│   ├── wifi/             # WiFi/AP 모드/캡티브 포털
│   ├── web/              # FastAPI 웹 UI
│   └── ota/              # OTA 업데이트 (미구현)
├── photos/local/         # 로컬 사진 저장소
├── assets/icons/         # 배터리 아이콘
├── scripts/              # 설치/복구 스크립트
├── tests/                # pytest 테스트
└── docs/                 # 스펙/구현 계획
```

## 설정 (config/settings.yaml)

```yaml
schedule:
  mode: "daily"            # daily / interval
  update_time: "06:00"
  timezone: "Asia/Seoul"
  interval_minutes: 1440

wifi:
  enabled: true
  ssid: ""
  password: ""

photo_selection:
  mode: "random"           # random / sequential

photo_sources:
  local:
    enabled: true
    path: "photos/local"

display:
  model: "7in3e"           # 7in3e / 13in3e
  rotation: 0              # 0 / 90 / 180 / 270

image_processing:
  fill_mode: "fit"         # fit / fill
  dithering: "floyd_steinberg"
  brightness: 1.0
  contrast: 1.35
  saturation: 1.5
  gamma: 1.25
  sharpness: 0.8
  warmth: 1.0
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
| DELETE | `/api/photos/{id}` | 사진 삭제 |
| GET | `/api/photos/{id}/thumbnail` | 썸네일 조회 |
| GET | `/api/photos/{id}/original` | 원본 조회 |
| POST | `/api/photos/{id}/crop` | 사진 크롭 |
| POST | `/api/system/photo-update` | 사진 업데이트 실행 |
| POST | `/api/system/apply` | 설정 적용 후 WiFi 재연결 |
| POST | `/api/system/shutdown` | 종료 |
| POST | `/api/image-preview/random` | 랜덤 사진 미리보기 |
| POST | `/api/image-preview/process` | 이미지 처리 미리보기 |

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
# install_service.sh가 자동으로 polkit 설정
# 수동 설정 필요 시:
sudo nano /etc/polkit-1/rules.d/10-network-manager.rules

# AP 모드 수동 종료
nmcli connection down Hotspot
nmcli connection down EinkFrame-Open

# 서비스 상태 확인
sudo systemctl status einkframe
sudo journalctl -u einkframe -f

# SPI 활성화
sudo raspi-config  # Interface Options > SPI > Enable
```
