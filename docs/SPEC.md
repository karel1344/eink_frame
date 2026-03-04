# E-Ink Photo Frame 스펙 문서

## 1. 프로젝트 개요

Raspberry Pi Zero 2 W와 컬러 e-ink 디스플레이를 사용하여 하루에 한 번 사진이 자동으로 바뀌는 초저전력 디지털 액자

**범위**: 이 프로젝트는 전자 회로 및 소프트웨어만 다룸 (케이스/프레임은 별도)

**핵심 특징**:
- Witty Pi 4를 통한 하드웨어 스케줄링으로 초저전력 구현
- 하루 1회만 부팅하여 사진 변경 후 완전 종료
- 다중 사진 소스 지원 (로컬 + Google Photos)
- 디스플레이 크기 호환을 위한 모듈화 설계

## 2. 하드웨어

### 2.1 메인 보드
- **Raspberry Pi Zero 2 W**
  - Quad-core 64-bit ARM Cortex-A53 @ 1GHz
  - 512MB RAM
  - WiFi 802.11 b/g/n
  - Bluetooth 4.2/BLE

### 2.2 전원 관리 모듈
- **Witty Pi 4 L3V7**
  - 하드웨어 RTC (실시간 시계)
  - 예약 부팅/종료 스케줄링
  - 배터리 전압 모니터링
  - 3.3V~24V 입력 지원

### 2.3 디스플레이
- **기본**: Waveshare 7.3" Spectra 6 (800×480)
- **확장 지원**: 13.3" Spectra 6 (1600×1200)
- **색상**: 6색 (Black, White, Red, Yellow, Blue, Green)
- **인터페이스**: SPI
- **새로고침 시간**: ~15-30초 (전체 화면)

### 2.4 전원
- **배터리**: 리튬이온 (Witty Pi 4 L3V7에서 관리)
- **전압 범위**: 3.0V ~ 4.2V (Witty Pi에서 모니터링)
- **참고**: 배터리 물리적 스펙(용량, 폼팩터)은 이 프로젝트 범위 외

### 2.5 물리 버튼
- **용도**: 웹 UI 모드 진입 (4.5, 5.4 참조)
- **연결**: GPIO 핀 (내장 풀업 저항 사용)
- **동작**: WiFi 연결 중 버튼 누르면 AP 모드로 전환

## 3. 소프트웨어 요구사항

### 3.1 운영체제
- Raspberry Pi OS Lite (64-bit)

### 3.2 프로그래밍 언어
- Python 3.11+

### 3.3 주요 라이브러리 (참고용, 구현 시 변경 가능)
| 라이브러리 | 용도 |
|-----------|------|
| `Pillow` | 이미지 처리 |
| `gpiozero` / `RPi.GPIO` | GPIO 제어 |
| `spidev` | SPI 통신 |
| `google-auth` | Google Photos API 인증 |
| `requests` | HTTP 통신 |
| `FastAPI` | 웹 설정 UI |
| `uvicorn` | ASGI 서버 (FastAPI 실행) |
| `Jinja2` | 웹 템플릿 |
| `python-multipart` | 파일 업로드 |
| `PyYAML` | 설정 파일 관리 |
| `aiosqlite` / `sqlite3` | 상태 관리 DB |
| `smbus2` | I2C 통신 (Witty Pi) |
| `python-networkmanager` | WiFi 연결 관리 (NetworkManager D-Bus) |

### 3.4 Witty Pi 연동
- `wittypi-python` 또는 직접 I2C 통신
- 배터리 전압 읽기
- 다음 부팅 스케줄 설정

## 4. 기능 요구사항

### 4.1 핵심 기능
- [x] 매일 지정된 시간에 자동 부팅 (Witty Pi 스케줄)
- [x] 사진 변경 후 자동 종료
- [x] 배터리 잔량 모니터링 및 저전압 보호 (4.7 참조)

### 4.2 사진 소스
- [x] **로컬 저장소** (`photos/local/`)
  - 웹 UI에서 직접 업로드한 사진
- [x] **Google Photos** (`photos/google/`)
  - 특정 앨범의 메타데이터 동기화 (SQLite DB)
  - Delta Sync: `last_sync_token` 저장하여 변경분만 동기화
  - 필요 시 다운로드 (미리 선정된 10장 중 필요한 것만)
  - 다운로드 후 디스플레이 크기로 리사이즈, 원본 삭제
  - 용량 초과 시 LRU 방식으로 오래된 것부터 삭제
  - 삭제 여부 트래킹 (재다운로드 가능)
- [x] **통합 선택**: 두 저장소에서 통합하여 랜덤 선택

### 4.3 사진 선택 방식
- [x] 순차적 (폴더 내 순서대로)
- [x] **랜덤** (기본값)
- [x] 날짜 기반 (오늘 날짜에 찍힌 사진 우선)

### 4.4 이미지 처리
- [x] 디스플레이 해상도에 맞게 자동 리사이즈
- [x] 6색 팔레트 디더링
- [x] 방향 자동 감지 (EXIF 기반)
- [x] 디더링 알고리즘: Floyd-Steinberg (기본)
- [x] **썸네일 사전 생성** (웹 UI 갤러리용)
  - 업로드/다운로드 시 즉시 생성 (200x200)
  - `.thumbnails/` 하위 디렉토리에 저장
  - 웹 UI 조회 시 원본 로드 없이 썸네일만 서빙

### 4.5 웹 UI 모드

웹 UI 진입 조건 및 모드:

#### 4.5.1 WEB_UI_MODE (WiFi 연결 유지 모드)
- [x] **물리 버튼 누름** 후 **WiFi 연결 성공** 시 진입
- Pi는 기존 WiFi에 연결된 채로 웹서버 실행
- 인터넷 연결 유지 → **Google OAuth 로그인, OTA 업데이트 등 온라인 기능 사용 가능**
- E-Ink에 Pi의 WiFi IP 표시 (스마트폰이 같은 WiFi에서 접근)
- Captive Portal 없음 (스마트폰이 같은 WiFi에 연결되어 있어야 함)

**WEB_UI_MODE 종료 방식:**
| 종료 방식 | 화면 처리 | 다음 단계 |
|-----------|-----------|-----------|
| 버튼 재누름 | 직전 사진 복원 | 종료 |
| 타임아웃 | 직전 사진 복원 | 종료 |
| "종료" 버튼 | 디폴트 이미지 | 종료 |
| "사진 업데이트" 버튼 | 새 사진 표시 | 사진 업데이트 후 종료 |

#### 4.5.2 AP_MODE (AP 핫스팟 모드)
- [x] **물리 버튼 누름** 후 **WiFi 연결 실패** 시 진입
- [x] **WiFi 연결 실패** 시 자동 전환 (버튼 없이도)
- [x] **에러 발생** 시 자동 전환
- AP 모드 활성화: `EinkFrame-XXXX` (XXXX는 기기 고유값)
- 스마트폰으로 AP 접속 시 웹 UI 자동 표시 (Captive Portal)
- [x] **통합 웹 UI**: WiFi 설정, 사진 관리, 시스템 설정 모두 가능
- [x] **오프라인 모드 설정**: WiFi 미사용, 로컬 사진만 사용 가능

**Captive Portal 구현 요구사항:**
- **DNS 하이재킹**: 모든 DNS 요청을 Pi IP로 리다이렉트 (dnsmasq 설정)
- **연결 확인 응답**: iOS/Android 연결 확인 URL에 적절히 응답
  - Android: `connectivitycheck.gstatic.com`, `clients3.google.com`
  - iOS: `captive.apple.com`, `www.apple.com/library/test/success.html`
- **HTTP 리다이렉트**: 모든 HTTP 요청을 웹 UI로 리다이렉트

**AP_MODE 종료 방식:**
| 종료 방식 | 화면 처리 | 설명 |
|-----------|-----------|------|
| 버튼 재누름 | 직전 사진 복원 | 실수로 진입 시 |
| 타임아웃 | 직전 사진 복원 | 사용자 이탈 |
| "종료" 버튼 | 디폴트 이미지 | 의도적 종료 |
| "적용 후 연결" | 새 사진 업데이트 | 설정 변경 후 (AP→WiFi 모드 전환) |

**동작 흐름**:
```
[정상 부팅 - 온라인 모드, 버튼 안 누름]
부팅 → WiFi 연결 시도 → 성공 → 사진 업데이트 → 종료

[버튼 누름 - WiFi 연결 성공]
부팅 → WiFi 연결 시도 (버튼 감지) → 성공
         ┌──────────────────────────────────────┐
         │       WEB_UI_MODE + 웹 UI             │
         │   E-ink에 Pi WiFi IP 주소 표시        │
         └──────────────────┬───────────────────┘
                            │
    ┌───────────┬───────────┼───────────┐
    ↓           ↓           ↓           ↓
 버튼 재누름  타임아웃    "종료"    "사진 업데이트"
    │           │         버튼         버튼
    ↓           ↓           ↓           ↓
 직전 사진   직전 사진   디폴트    사진 업데이트
   복원       복원      이미지     후 종료
    ↓           ↓           ↓
   종료        종료        종료

[버튼 누름 - WiFi 연결 실패 / WiFi 실패 / 에러 발생]
         ┌──────────────────────────────────────┐
         │            AP_MODE + 웹 UI            │
         │      E-ink에 AP 접속 안내 표시        │
         └──────────────────┬───────────────────┘
                            │
    ┌───────────┬───────────┼───────────┬───────────┐
    ↓           ↓           ↓           ↓           ↓
 버튼 재누름  타임아웃    "종료"    "적용 후 연결"  에러표시
    │           │         버튼         버튼       상태
    │           │           │           │           │
    ↓           ↓           ↓           │           │
 직전 사진   직전 사진   디폴트      AP 중지        │
   복원       복원      이미지         │           │
    │           │           │           ↓           │
    └───────────┴───────────┴──→ WiFi 연결 ←───────┘
                            │       시도
                            │         │
                            │    ┌────┴────┐
                            │    ↓         ↓
                            │  성공      실패
                            │    │         │
                            │    ↓         │
                            │ 사진 업데이트 │
                            │    │         │
                            ↓    ↓         ↓
                          종료 ←─┴─── AP 모드

[정상 부팅 - 오프라인 모드]
부팅 → (WiFi 건너뜀) → 로컬 사진 업데이트 → 종료
         ↓ (버튼 누름)
      AP 모드 (오프라인이므로 WiFi 연결 시도 없음)
```

### 4.6 웹 설정 UI
- [x] 사진 업데이트 시간 설정
- [x] 사진 소스 선택/설정
- [x] Google Photos 연동 설정
- [x] 사진 선택 모드 변경
- [x] 수동 사진 변경 트리거
- [x] 시스템 상태 확인 (배터리, 마지막 업데이트 등)
- [x] **오프라인 모드 설정**
  - WiFi 사용 ON/OFF 토글
  - OFF 시: 로컬 사진만 사용, Google Photos/OTA 비활성화
- [x] **사진 업로드/관리**
  - 웹에서 직접 사진 업로드 (드래그앤드롭 지원)
  - 업로드된 사진 목록 보기 (썸네일)
  - 사진 삭제
  - 지원 포맷: JPEG, PNG, HEIC
  - 자동 리사이즈 (원본 보존 옵션)
  - **메모리 최적화**:
    - 업로드 파일 크기 제한 (20MB)
    - 스트리밍 업로드 (디스크에 먼저 저장)
    - 이미지 처리 시 청크 단위 로드
- [x] **시스템 제어**
  - "종료" 버튼: 디폴트 이미지 표시 후 종료
  - "적용 후 연결" 버튼: 설정 저장 → WiFi 연결 → 사진 업데이트 → 종료

### 4.7 배터리 관리
- **저전압 임계값**: 3.3V
- **충전 필요 표시**: 화면 우측 상단 배터리 아이콘
- **긴급 종료**: 3.0V 이하 시 강제 종료

### 4.8 E-ink 상태 표시
사진 외에 시스템 상태를 화면에 표시:
- [x] **WiFi 설정 모드**: AP 모드 진입 시 SSID, 접속 방법 안내 표시
- [x] **에러 상태**: 네트워크 오류, Google API 오류 등 발생 시 에러 메시지 표시
- [x] **배터리 부족**: 우측 상단 충전 필요 아이콘
- [x] **업데이트 완료**: (선택) 사진 변경 완료 시 잠시 표시

### 4.9 OTA 업데이트
- [x] 웹 UI에서 새 버전 확인
- [x] GitHub Release 또는 지정된 서버에서 업데이트 다운로드
- [x] 업데이트 설치 및 자동 재시작
- [x] 롤백 기능 (업데이트 실패 시 이전 버전으로 복구)

## 5. 시스템 아키텍처

### 5.1 부팅 시퀀스 (간소화)

> **참고**: 상세 흐름은 5.4 상태머신 참조

```
┌─────────────────────────────────────────────────────────────────┐
│                        Witty Pi 스케줄                          │
│                    (예: 매일 06:00 부팅)                         │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  [INIT] 시스템 초기화, 배터리 확인                                 │
│                               │                                  │
│                               ▼                                  │
│  [WIFI_CONNECT] WiFi 연결 시도 (버튼 눌림 상태 감시)                │
│         │              │              │                          │
│      성공 ↓         실패 ↓         버튼 ↓                         │
│                               │                                  │
│  [PHOTO_UPDATE]          [AP_MODE]                               │
│  사진 선택/처리/표시      웹 UI 실행                               │
│         │                     │                                  │
│         ▼                     ▼                                  │
│  [SCHEDULE] → [SHUTDOWN]  ← 종료/적용                            │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 웹 UI 모드 (간소화)

> **참고**: 상세 흐름은 5.4 상태머신 참조

```
┌─────────────────────────────────────────────────────────────────┐
│  진입 조건: 물리 버튼 누름 / WiFi 연결 실패 / 에러 발생             │
│  1. AP 모드 활성화 (EinkFrame-XXXX)                              │
│  2. E-ink에 AP 접속 안내 표시                                    │
│  3. FastAPI 웹서버 실행 (Captive Portal)                        │
│  4. 종료 방식에 따른 처리:                                        │
│     - 버튼 재누름/타임아웃: 직전 사진 복원 → 종료                   │
│     - "종료" 버튼: 디폴트 이미지 → 종료                            │
│     - "적용 후 연결": AP 중지 → WiFi 연결 → 사진 업데이트 → 종료   │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 모듈 구조
```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│                    (진입점, 흐름 제어)                            │
└─────────────────────────────────────────────────────────────────┘
    │        │        │        │        │        │        │
    ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌───────┐┌───────┐┌───────┐┌───────┐┌───────┐┌───────┐┌───────┐
│config ││ photo ││display││ power ││ wifi  ││  ota  ││button │
│Manager││ source││ Driver││Manager││Manager││Updater││Handler│
└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘
             │         │                 │
    ┌────────┼─────────┘                 │
    ▼        ▼                           ▼
┌────────┐┌────────┐┌────────┐     ┌────────┐
│- Local ││- 7.3"  ││database│     │- AP    │
│- Google││- 13.3" ││(SQLite)│     │- Portal│
└────────┘└────────┘└────────┘     └────────┘
```

### 5.4 상태머신

#### 5.4.1 상태 (States)

| 상태 | 설명 |
|------|------|
| `INIT` | 시스템 초기화, 하드웨어 점검 |
| `WIFI_CONNECT` | WiFi 연결 시도 (버튼 눌림 상태 감시) |
| `WEB_UI_MODE` | WiFi 연결된 상태에서 웹 UI 실행 (버튼 누름 + WiFi 성공 시) |
| `AP_MODE` | AP 핫스팟 모드 + 웹 UI 실행 중 (WiFi 실패 / 에러 시) |
| `PHOTO_UPDATE` | 사진 선택 → 처리 → 디스플레이 |
| `SCHEDULE` | 다음 부팅 스케줄 설정 |
| `SHUTDOWN` | 시스템 종료 |
| `ERROR` | 에러 처리 및 표시 |

#### 5.4.2 이벤트 (Events)

| 이벤트 | 설명 |
|--------|------|
| `INIT_COMPLETE` | 초기화 완료 |
| `BUTTON_PRESSED` | 물리 버튼 눌림 감지 → `web_ui_requested` 플래그 설정, WiFi 시도는 계속 |
| `WIFI_SUCCESS` | WiFi 연결 성공 (web_ui_requested=False → PHOTO_UPDATE) |
| `WIFI_SUCCESS_WEB_UI` | WiFi 연결 성공 + 버튼 눌렸음 (web_ui_requested=True → WEB_UI_MODE) |
| `WIFI_FAIL` | WiFi 연결 실패/타임아웃 → AP_MODE |
| `OFFLINE_MODE` | 오프라인 모드 (WiFi 비활성화) |
| `WEB_UI_BUTTON_EXIT` | WEB_UI_MODE 중 버튼 재누름 |
| `WEB_UI_TIMEOUT` | WEB_UI_MODE 타임아웃 |
| `WEB_UI_SHUTDOWN` | WEB_UI_MODE에서 "종료" 선택 |
| `WEB_UI_UPDATE` | WEB_UI_MODE에서 "사진 업데이트" 선택 |
| `AP_BUTTON_EXIT` | AP_MODE 중 버튼 재누름 |
| `AP_TIMEOUT` | AP_MODE 타임아웃 |
| `AP_USER_SHUTDOWN` | AP_MODE 웹 UI에서 "종료" 선택 |
| `AP_USER_APPLY` | AP_MODE 웹 UI에서 "적용 후 연결" 선택 |
| `UPDATE_COMPLETE` | 사진 업데이트 완료 |
| `SCHEDULE_SET` | 스케줄 설정 완료 |
| `ERROR_OCCURRED` | 에러 발생 |
| `ERROR_HANDLED` | 에러 처리 완료 |

#### 5.4.3 전이 다이어그램

```
              ┌──────────┐
              │   INIT   │
              └────┬─────┘
                   │ INIT_COMPLETE
                   ▼
            ┌──────────────┐◄───────────────────────────────┐
            │ WIFI_CONNECT │ ◄─── 버튼 눌림 상태 감시         │
            └──────┬───────┘  (BUTTON_PRESSED: 플래그만 설정) │
                   │                                         │
   ┌───────────────┼───────────────┬──────────────┐          │
   │               │               │              │          │
   │ WIFI_SUCCESS  │ WIFI_SUCCESS  │ WIFI_FAIL    │ OFFLINE  │
   │ (버튼 안 누름) │ _WEB_UI       │              │ MODE     │
   │               │ (버튼 눌렸음) │              │          │
   │               ▼               ▼              │          │
   │   ┌──────────────────┐  ┌──────────┐         │          │
   │   │  WEB_UI_MODE     │  │ AP_MODE  │◄────────┘          │
   │   │  (WiFi 연결 유지) │  │ (핫스팟) │                    │
   │   └────────┬─────────┘  └────┬─────┘                    │
   │            │                 │                           │
   │  ┌─────────┼──────────┐  ┌───┴──────────────┬────────┐  │
   │  │         │          │  │                  │        │  │
   │  │WEB_UI   │WEB_UI    │  │AP_BUTTON_EXIT    │AP_USER │  │
   │  │BUTTON   │SHUTDOWN  │  │AP_TIMEOUT        │APPLY   │  │
   │  │EXIT /   │          │  │AP_USER_SHUTDOWN  │        │  │
   │  │TIMEOUT  │          │  │                  │        │  │
   │  │         │          │  │직전 사진 복원 /   │AP 중지  │  │
   │  │직전사진  │디폴트    │  │디폴트 이미지      │WiFi 연결│  │
   │  │복원     │이미지    │  │                  │시도     │  │
   │  ▼         ▼          │  ▼                  ▼        │  │
   │  ┌──────────────────┐ │  ┌──────────────────────┐   │  │
   │  │     SHUTDOWN     │ │  │       SHUTDOWN        │   │  │
   │  └──────────────────┘ │  └──────────────────────┘   │  │
   │                       │                              │  │
   │  WEB_UI_UPDATE        │                   ───────────┘  │
   │  ↓                    │                   │             │
   │                       │                   ▼             │
   │                       │         WiFi 연결 시도           │
   │                       │              │                  │
   │                       │       ┌──────┴──────┐           │
   │                       │       ↓              ↓          │
   │                       │    성공            실패          │
   │                       │       │              │          │
   ↓                       ↓       ↓              ↓          │
 ┌──────────────────────────────────────┐      AP_MODE       │
 │             PHOTO_UPDATE             │                    │
 └──────────────────┬───────────────────┘                    │
                    │ UPDATE_COMPLETE                         │
                    ▼                                         │
             ┌──────────┐                                     │
             │ SCHEDULE │                                     │
             └────┬─────┘                                     │
                  │ SCHEDULE_SET                              │
                  ▼                                           │
             ┌──────────┐                                     │
             │ SHUTDOWN │                                     │
             └──────────┘                                     │
                                                             │
          ┌──────────┐                                        │
          │  ERROR   │──────────────────────────────────────►│
          └──────────┘  ERROR_HANDLED → AP_MODE              │
            E-ink에 에러 표시                                  │
```

#### 5.4.4 전이 테이블

| 현재 상태 | 이벤트 | 다음 상태 | 액션 |
|-----------|--------|-----------|------|
| `INIT` | `INIT_COMPLETE` | `WIFI_CONNECT` | 버튼 상태 감시 시작 |
| `INIT` | `ERROR_OCCURRED` | `ERROR` | 에러 로깅 |
| `WIFI_CONNECT` | `BUTTON_PRESSED` | `WIFI_CONNECT` (유지) | `web_ui_requested=True` 플래그 설정, WiFi 시도 계속 |
| `WIFI_CONNECT` | `WIFI_SUCCESS` (web_ui_requested=False) | `PHOTO_UPDATE` | 버튼 상태 감시 종료 |
| `WIFI_CONNECT` | `WIFI_SUCCESS_WEB_UI` (web_ui_requested=True) | `WEB_UI_MODE` | 웹서버 시작, E-Ink에 WiFi IP 표시 |
| `WIFI_CONNECT` | `WIFI_FAIL` | `AP_MODE` | AP 시작, 안내 화면 표시 |
| `WIFI_CONNECT` | `OFFLINE_MODE` | `PHOTO_UPDATE` | 버튼 상태 감시 종료 |
| `WEB_UI_MODE` | `WEB_UI_BUTTON_EXIT` | `SHUTDOWN` | 직전 사진 복원 표시 |
| `WEB_UI_MODE` | `WEB_UI_TIMEOUT` | `SHUTDOWN` | 직전 사진 복원 표시 |
| `WEB_UI_MODE` | `WEB_UI_SHUTDOWN` | `SHUTDOWN` | 디폴트 이미지 표시 |
| `WEB_UI_MODE` | `WEB_UI_UPDATE` | `PHOTO_UPDATE` | 웹서버 종료 후 사진 업데이트 시작 |
| `AP_MODE` | `AP_BUTTON_EXIT` | `SHUTDOWN` | 직전 사진 복원 표시 |
| `AP_MODE` | `AP_TIMEOUT` | `SHUTDOWN` | 직전 사진 복원 표시 |
| `AP_MODE` | `AP_USER_SHUTDOWN` | `SHUTDOWN` | 디폴트 이미지 표시 |
| `AP_MODE` | `AP_USER_APPLY` | `WIFI_CONNECT` | AP 중지, WiFi 설정 저장 |
| `PHOTO_UPDATE` | `UPDATE_COMPLETE` | `SCHEDULE` | - |
| `PHOTO_UPDATE` | `ERROR_OCCURRED` | `ERROR` | 에러 로깅 |
| `SCHEDULE` | `SCHEDULE_SET` | `SHUTDOWN` | - |
| `SCHEDULE` | `ERROR_OCCURRED` | `ERROR` | 에러 로깅 |
| `ERROR` | `ERROR_HANDLED` | `AP_MODE` | E-ink에 에러 표시 |

#### 5.4.5 오프라인 모드

WiFi가 비활성화된 경우 (`wifi.enabled: false`):
- `WIFI_CONNECT` 상태에서 연결 시도 없이 즉시 `OFFLINE_MODE` 이벤트 발생
- 버튼 눌림 상태는 여전히 감시 (AP 모드 진입 가능)
- 로컬 사진만 사용
- Google Photos 동기화 비활성화
- OTA 업데이트 비활성화

#### 5.4.6 DB 저장 항목

상태머신 관련 DB 저장 항목:
- `last_displayed_photo`: 직전에 표시된 사진 경로 (AP 모드 종료 시 복원용)
- `last_sync_token`: Google Photos Delta Sync 토큰

#### 5.4.7 PHOTO_UPDATE 내부 단계

`PHOTO_UPDATE` 상태는 내부적으로 다음 단계를 순차 처리:

```
PHOTO_UPDATE
    │
    ├─ 1. Google Photos 메타데이터 동기화 (온라인 모드 시)
    │      └─ Delta Sync (last_sync_token 사용)
    │
    ├─ 2. 다음 사진 선택 (로컬 + Google 통합)
    │      └─ 랜덤 / 순차 / 날짜 기반
    │
    ├─ 3. 필요 시 다운로드 (Google 사진인 경우)
    │      └─ 이미 캐시되어 있으면 스킵
    │
    ├─ 4. 이미지 처리
    │      └─ 리사이즈, 6색 디더링, EXIF 회전
    │
    ├─ 5. 배터리 아이콘 오버레이 (저전압 시)
    │
    └─ 6. E-ink 디스플레이 업데이트
```

**오프라인 모드일 때:**
- 1번(동기화), 3번(다운로드) 단계 스킵
- 로컬 사진 + 이미 캐시된 Google 사진만 사용

**에러 발생 시:**
- 어느 단계에서든 에러 발생 시 `ERROR_OCCURRED` 이벤트
- `ERROR` 상태로 전이 후 `AP_MODE` 진입

#### 5.4.8 INIT 내부 단계

`INIT` 상태는 내부적으로 다음 단계를 순차 처리:

```
INIT
    │
    ├─ 1. 하드웨어 초기화
    │      └─ GPIO, SPI, I2C 설정
    │
    ├─ 2. 설정 파일 로드
    │      └─ config/settings.yaml 읽기
    │
    ├─ 3. 배터리 전압 확인
    │      └─ 긴급 종료 임계값(3.0V) 이하 시 즉시 SHUTDOWN
    │
    ├─ 4. 데이터베이스 연결
    │      └─ SQLite DB 초기화/연결
    │
    └─ 5. 오프라인 모드 여부 확인
           └─ wifi.enabled 설정 확인
```

**에러 발생 시:**
- 설정 파일 로드 실패, DB 연결 실패 등 → `ERROR_OCCURRED`

#### 5.4.9 스레드 아키텍처 (상태머신 + FastAPI)

상태머신과 FastAPI 웹서버의 충돌 방지를 위한 스레드 분리 설계:

웹서버는 `WEB_UI_MODE`와 `AP_MODE` 두 상태 모두에서 실행되며, 네트워크 설정만 다름:
- `WEB_UI_MODE`: WiFi 연결 유지, 포트 8080, Captive Portal 없음
- `AP_MODE`: AP 핫스팟 활성화, 포트 80, Captive Portal DNS 실행

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Thread                               │
│                      (상태머신 실행)                              │
│                                                                  │
│  ┌─────────┐    ┌─────────┐    ┌──────────────┐  ┌──────────┐  │
│  │  INIT   │───►│WIFI_CONN│───►│WEB_UI_MODE   │  │AP_MODE   │  │
│  └─────────┘    └─────────┘    │또는 AP_MODE  │  │          │  │
│                                └──────┬───────┘  └──────────┘  │
│                                       │                         │
│                                웹서버 시작                       │
│                                       │                         │
└───────────────────────────────────────┼─────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 ▼                 │
                    │  ┌─────────────────────────────┐  │
                    │  │       Web Thread            │  │
                    │  │    (FastAPI + uvicorn)      │  │
                    │  │                             │  │
                    │  │  HTTP 요청 처리              │  │
                    │  │  /api/system/apply          │  │
                    │  │  /api/system/shutdown       │  │
                    │  └──────────────┬──────────────┘  │
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      │
                         ┌────────────▼────────────┐
                         │      Event Queue        │
                         │  (thread-safe queue)    │
                         │                         │
                         │  - AP_USER_APPLY        │
                         │  - AP_USER_SHUTDOWN     │
                         │  - AP_BUTTON_EXIT       │
                         └────────────┬────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 ▼                 │
                    │  Main Thread에서 이벤트 수신      │
                    │  → 상태 전이 처리                  │
                    └───────────────────────────────────┘
```

**구현 방식:**

```python
import queue
import threading
import uvicorn

# 스레드 간 통신용 큐
event_queue = queue.Queue()

# uvicorn 서버 인스턴스 (programmatic shutdown용)
server = None

def run_web_server():
    global server
    config = uvicorn.Config(app, host="0.0.0.0", port=80, log_level="info")
    server = uvicorn.Server(config)
    server.run()

# AP_MODE 상태 진입 시
def enter_ap_mode():
    # 1. 웹서버 스레드 시작
    web_thread = threading.Thread(target=run_web_server)
    web_thread.start()

    # 2. 이벤트 대기 (blocking)
    while True:
        try:
            event = event_queue.get(timeout=1)
            if event in [Event.AP_USER_APPLY, Event.AP_USER_SHUTDOWN]:
                break
        except queue.Empty:
            # 타임아웃 체크, 버튼 체크
            pass

    # 3. 웹서버 종료 (signal이 아닌 internal flag로 제어)
    server.should_exit = True
    web_thread.join(timeout=5)

    return event

# FastAPI 엔드포인트
@app.post("/api/system/apply")
def apply_settings():
    event_queue.put(Event.AP_USER_APPLY)
    return {"status": "accepted"}
```

**주요 고려사항:**
- `queue.Queue`는 thread-safe
- 메인 스레드에서 타임아웃, 버튼 눌림 상태도 함께 처리
- **웹서버 종료는 signal이 아닌 `server.should_exit` flag로 제어** (thread 내 uvicorn 실행 시 필수)
- 공유 자원(설정, DB) 접근 시 락(lock) 사용

#### 5.4.10 SQLite 동시성 처리

**동시 접근 시나리오:**
- AP_MODE 중 Main thread + FastAPI thread만 동시 실행
- PHOTO_UPDATE의 Google Photos Sync는 AP_MODE와 겹치지 않음

**해결책: WAL 모드 + timeout**

```python
import sqlite3

def get_connection():
    conn = sqlite3.connect(
        'state.db',
        timeout=10.0,  # lock 대기 최대 10초
        check_same_thread=False  # 멀티스레드 허용
    )
    conn.execute('PRAGMA journal_mode=WAL')  # WAL 모드 활성화
    return conn
```

**WAL 모드 특징:**
- 읽기와 쓰기 동시 가능
- 읽기끼리 완전 병렬 처리
- 쓰기 충돌 시에만 짧은 대기 (timeout으로 제어)

## 6. 디렉토리 구조

```
eink_frame/
├── src/
│   ├── __init__.py
│   ├── main.py                 # 진입점
│   ├── state_machine.py        # 상태머신 구현
│   ├── config.py               # 설정 관리
│   ├── power_manager.py        # Witty Pi, 배터리 관리
│   ├── image_processor.py      # 이미지 처리, 디더링
│   ├── display/                # 디스플레이 드라이버 (모듈화)
│   │   ├── __init__.py
│   │   ├── base.py             # 추상 기본 클래스
│   │   ├── spectra6_7in3.py    # 7.3인치 드라이버
│   │   └── spectra6_13in3.py   # 13.3인치 드라이버
│   ├── photo_source/           # 사진 소스 (모듈화)
│   │   ├── __init__.py
│   │   ├── base.py             # 추상 기본 클래스
│   │   ├── local.py            # 로컬 파일시스템
│   │   └── google_photos.py    # Google Photos API
│   ├── web/                    # 웹 설정 UI
│   │   ├── __init__.py
│   │   ├── app.py              # FastAPI 앱
│   │   ├── routes.py           # API 라우트
│   │   └── templates/          # HTML 템플릿
│   ├── wifi/                   # WiFi 관리
│   │   ├── __init__.py
│   │   ├── manager.py          # WiFi 연결 관리
│   │   ├── ap_mode.py          # AP 모드 (hostapd, dnsmasq)
│   │   └── captive_portal.py   # Captive Portal 서버
│   ├── ota/                    # OTA 업데이트
│   │   ├── __init__.py
│   │   ├── updater.py          # 업데이트 다운로드/설치
│   │   └── version.py          # 버전 관리
│   ├── button.py               # 물리 버튼 처리
│   ├── database.py             # SQLite DB 관리
│   └── status_display.py       # E-ink 상태 메시지 표시
├── config/
│   ├── settings.yaml           # 사용자 설정
│   └── google_credentials.json # Google API 인증 (gitignore)
├── assets/
│   ├── icons/                  # 배터리 아이콘 등
│   └── default.png             # 디폴트 이미지 (종료 시 표시)
├── photos/
│   ├── local/                  # 웹 UI에서 업로드한 사진
│   │   └── .thumbnails/        # 로컬 사진 썸네일 캐시
│   └── google/                 # Google Photos에서 다운로드한 사진
│       └── .thumbnails/        # Google 사진 썸네일 캐시
├── data/
│   └── einkframe.db            # SQLite DB (사진 메타데이터, 상태)
├── logs/                       # 로그 파일
├── tests/
│   ├── test_state_machine.py   # 상태머신 테스트
│   ├── test_image_processor.py # 이미지 처리 테스트
│   ├── test_display.py         # 디스플레이 드라이버 테스트
│   ├── test_photo_source.py    # 사진 소스 테스트
│   ├── test_database.py        # DB 테스트
│   ├── test_wifi.py            # WiFi 관리 테스트
│   ├── test_ota.py             # OTA 업데이트 테스트
│   ├── test_power_manager.py   # 전원 관리 테스트
│   ├── test_button.py          # 버튼 테스트
│   └── test_web_api.py         # 웹 API 테스트
├── scripts/
│   ├── install.sh              # 설치 스크립트
│   └── wittypi_schedule.sh     # Witty Pi 스케줄 설정
├── docs/
│   ├── SPEC.md                 # 이 문서
│   └── SETUP.md                # 설치 가이드
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 7. 설정 파일

```yaml
# config/settings.yaml

# 디스플레이 설정
display:
  model: "7in3e"                 # 7in3e / 13in3k
  rotation: 0                    # 0 / 90 / 180 / 270  (90/270이면 portrait 자동 처리)

# 스케줄 설정
schedule:
  update_time: "06:00"           # 24시간 형식 (Witty Pi 스케줄)
  timezone: "Asia/Seoul"

# 사진 소스 설정
photo_sources:
  local:
    enabled: true
    path: "/home/pi/eink_frame/photos/local"

  google_photos:
    enabled: true
    album_id: "YOUR_ALBUM_ID"
    path: "/home/pi/eink_frame/photos/google"

# 사진 선택 설정
photo_selection:
  mode: "random"                 # sequential / random / date_based
  avoid_repeats: true            # 최근 N장 반복 방지
  repeat_threshold: 30           # 반복 방지할 사진 수

# 이미지 처리 설정
image_processing:
  dithering: "floyd_steinberg"   # floyd_steinberg / atkinson / none
  auto_rotate: true              # EXIF 기반 자동 회전
  fill_mode: "fit"               # fit (레터박스) / fill (크롭)

# 배터리 설정
battery:
  low_voltage_threshold: 3.3     # 저전압 경고 임계값 (V)
  critical_voltage: 3.0          # 긴급 종료 임계값 (V)
  show_indicator: true           # 배터리 부족 아이콘 표시

# WiFi 설정
wifi:
  enabled: true                  # false면 오프라인 모드 (로컬 사진만 사용)
  ssid: ""                       # 저장된 WiFi SSID
  password: ""                   # 저장된 WiFi 비밀번호
  connection_timeout: 30         # 연결 시도 타임아웃 (초)
  retry_count: 3                 # 재시도 횟수

# 웹 UI / AP 모드 설정
web_ui:
  ap_ssid_prefix: "EinkFrame"    # AP SSID 접두사 (뒤에 기기ID 붙음)
  ap_password: ""                # AP 비밀번호 (빈값이면 오픈)
  port: 80                       # 웹 UI 포트 (Captive Portal)
  timeout: 600                   # 웹 UI 모드 자동 종료 타임아웃 (초, 0이면 무제한)

# 물리 버튼 설정
button:
  gpio_pin: 17                   # GPIO 핀 번호
  pull_up: true                  # 풀업 저항 사용
  hold_time: 3                   # 길게 누르기 인식 시간 (초)

# OTA 업데이트 설정
ota:
  enabled: true
  update_url: "https://api.github.com/repos/USER/eink_frame/releases/latest"
  auto_check: false              # 부팅 시 자동 업데이트 확인
  backup_before_update: true     # 업데이트 전 백업 생성

# 저장소 설정
storage:
  google_photos_max_mb: 500      # Google Photos 다운로드 최대 용량
  local_photos_max_mb: 500       # 로컬 업로드 최대 용량
  prefetch_count: 10             # 미리 선정할 사진 수

# 로깅 설정
logging:
  level: "INFO"                  # DEBUG / INFO / WARNING / ERROR
  max_files: 5                   # 로그 파일 최대 개수
  max_size_mb: 1                 # 로그 파일당 최대 크기
```

## 8. API 설계 (웹 UI)

### 8.1 REST API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/status` | 시스템 상태 (배터리, 마지막 업데이트 등) |
| GET | `/api/settings` | 현재 설정 조회 |
| PUT | `/api/settings` | 설정 변경 |
| POST | `/api/refresh` | 수동 사진 업데이트 트리거 |
| GET | `/api/photos` | 로컬 사진 목록 (썸네일 URL 포함) |
| GET | `/api/photos/{id}` | 개별 사진 정보 |
| GET | `/api/photos/{id}/thumbnail` | 썸네일 이미지 |
| POST | `/api/photos/upload` | 사진 업로드 (multipart/form-data) |
| DELETE | `/api/photos/{id}` | 사진 삭제 |
| GET | `/api/google/auth` | Google 인증 시작 |
| POST | `/api/google/callback` | Google OAuth 콜백 |
| GET | `/api/wifi/scan` | 주변 WiFi 네트워크 스캔 (AP 모드에서 가능) |
| POST | `/api/system/shutdown` | 시스템 종료 (디폴트 이미지 표시) |
| POST | `/api/system/apply` | 설정 적용 후 WiFi 연결 → 사진 업데이트 |
| GET | `/api/update/check` | 새 버전 확인 |
| POST | `/api/update/install` | 업데이트 설치 |
| GET | `/api/update/version` | 현재 버전 정보 |

### 8.2 응답 예시

```json
// GET /api/status
{
  "battery": {
    "voltage": 3.85,
    "percentage": 72,
    "charging": false
  },
  "last_update": "2026-03-02T06:00:15+09:00",
  "next_update": "2026-03-03T06:00:00+09:00",
  "current_photo": {
    "source": "google_photos",
    "name": "family_photo_2025.jpg"
  },
  "wifi_connected": true
}

// GET /api/photos
{
  "photos": [
    {
      "id": "abc123",
      "filename": "family_2025.jpg",
      "uploaded_at": "2026-03-01T10:30:00+09:00",
      "size_bytes": 2048576,
      "dimensions": {"width": 4032, "height": 3024},
      "thumbnail_url": "/api/photos/abc123/thumbnail"
    }
  ],
  "total": 42,
  "storage_used_mb": 156,
  "storage_available_mb": 844
}

// POST /api/photos/upload
// Request: multipart/form-data with "file" field
// Response:
{
  "success": true,
  "photo": {
    "id": "def456",
    "filename": "uploaded_photo.jpg"
  }
}
```

## 9. 비기능 요구사항

### 9.1 전력 소비
| 상태 | 소비 전력 |
|------|----------|
| 완전 종료 (Witty Pi 대기) | ~10μA |
| 부팅 + WiFi + 처리 | ~200-400mA |
| E-ink 새로고침 | ~50-100mA |

### 9.2 배터리 수명 예측 (예시)
- 3000mAh 배터리 기준
- 하루 1회 업데이트, 평균 2분 동작
- 예상 수명: **수주 ~ 수개월**

### 9.3 안정성
- 네트워크 오류 시: 로컬 캐시 사진 사용
- Google API 실패 시: 로컬 소스로 폴백
- 배터리 저전압 시: 안전 종료
- Watchdog 타이머로 무한루프 방지

### 9.4 메모리 관리 (512MB RAM)

**설계 원칙**: 웹 서버와 이미지 처리가 동시에 실행되지 않도록 분리

| 모드 | 주요 프로세스 | 예상 메모리 |
|------|---------------|-------------|
| 사진 업데이트 | Pillow 이미지 처리 | ~200-300MB |
| AP 모드 | FastAPI + uvicorn + hostapd + dnsmasq | ~150-200MB |

**최적화 전략**:
- AP 모드 종료 후 이미지 처리 시작 (동시 실행 방지)
- 썸네일 사전 생성 (웹 UI에서 원본 로드 방지)
- 업로드 시 스트리밍 저장 + 청크 단위 처리
- 업로드 파일 크기 제한 (20MB)
- 안전망으로 256MB swap 권장

### 9.5 로깅
- 로그 파일 위치: `logs/einkframe.log`
- 로그 로테이션: 최대 5개 파일, 각 1MB
- 로그 레벨: INFO (기본), DEBUG (설정 가능)

## 10. 마일스톤

| 단계 | 내용 | 상태 |
|------|------|------|
| 1 | 하드웨어 구매 (Pi, 디스플레이, Witty Pi, 배터리) | [ ] |
| 2 | 기본 디스플레이 드라이버 구현 및 테스트 | [ ] |
| 3 | Witty Pi 스케줄링 연동 | [ ] |
| 4 | 이미지 처리 파이프라인 (리사이즈, 디더링) | [ ] |
| 5 | 로컬 사진 소스 구현 | [ ] |
| 6 | Google Photos 연동 | [ ] |
| 7 | 배터리 모니터링 및 아이콘 오버레이 | [ ] |
| 8 | WiFi 프로비저닝 (Captive Portal) 구현 | [ ] |
| 9 | 웹 UI 모드 구현 (AP 모드, 버튼) | [ ] |
| 10 | E-ink 상태 표시 기능 구현 | [ ] |
| 11 | OTA 업데이트 기능 구현 | [ ] |
| 12 | 전체 통합 테스트 | [ ] |
| 13 | 실사용 테스트 | [ ] |

## 11. 결정 필요 사항 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| 디스플레이 모델 | ✅ | Spectra 6 7.3" (13.3" 호환) |
| 사진 소스 | ✅ | 로컬 + Google Photos |
| 전원 방식 | ✅ | 배터리 + Witty Pi 4 L3V7 |
| 배터리 | ✅ | Witty Pi에서 관리 (물리 스펙은 범위 외) |
| 사진 선택 방식 기본값 | ✅ | 랜덤 |
| 웹 UI 프레임워크 | ✅ | FastAPI |
| E-ink 상태 표시 | ✅ | WiFi 설정, 에러, 배터리 표시 |
| OTA 업데이트 | ✅ | GitHub Release 기반 |
| 상태 관리 DB | ✅ | SQLite |
| 저장소 구조 | ✅ | 로컬/Google 분리, 선택은 통합 |
| 웹 UI 접속 방식 | ✅ | AP 모드 (버튼 또는 WiFi 실패 시) |
| 시스템 아키텍처 | ✅ | 상태머신 기반 |
| 오프라인 모드 | ✅ | WiFi 비활성화 옵션, 로컬 사진만 사용 |
| 버튼 누름 시 동작 | ✅ | WiFi 연결 계속 시도 → 성공 시 WEB_UI_MODE, 실패 시 AP_MODE |
| AP_MODE 종료 방식 | ✅ | 버튼/타임아웃(직전사진), 종료(디폴트), 적용(새사진) |
| WEB_UI_MODE 종료 방식 | ✅ | 버튼/타임아웃(직전사진→종료), 종료(디폴트), 사진업데이트(PHOTO_UPDATE) |
| AP→WiFi 전환 | ✅ | 재부팅 없이 모드 전환 |
| 스레드 아키텍처 | ✅ | 상태머신(메인) + FastAPI(별도 스레드) + 이벤트 큐 |

---

*마지막 업데이트: 2026-03-04*
