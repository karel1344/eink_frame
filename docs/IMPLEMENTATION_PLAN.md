# E-Ink Photo Frame 구현 계획

## 현재 상태 요약

| 카테고리 | 구현율 |
|----------|--------|
| 인프라/설정 | 100% |
| WiFi/AP 모드 | 80% |
| 웹 UI | 90% |
| 사진 소스 | 75% |
| 이미지 처리 | 100% |
| 디스플레이 드라이버 | 100% |
| 전원 관리 | 100% |
| 상태머신 | 100% |
| OTA 업데이트 | 0% |
| 에셋/스크립트 | 60% |
| 저장소/로깅 | 0% |

---

## Phase 1: 인프라 (Infrastructure) - 100% 완료

### 완료 ✅

- [x] **config.py** - 설정 파일 관리
  - YAML 설정 로드/저장
  - 기본값 처리
  - 프로퍼티 접근자 (display_model, display_rotation, image_fill_mode 등)

- [x] **main.py** - 진입점
  - 개발/프로덕션 모드 분기
  - uvicorn 웹서버 실행

- [x] **einkframe.py** - 최상위 실행 파일
  - `--dev` 플래그로 개발 모드 (포트 8000, reload=True)
  - `--frame` 플래그로 사진 표시만 실행
  - `--dry-run` 플래그로 디버그 출력 (debug_output.png)
  - 플래그 없으면 프로덕션 모드 (상태머신)

- [x] **startup.py** - 시작 시퀀스
  - WiFi 연결 시도
  - AP 모드 폴백
  - 복구 플래그 체크

- [x] **wifi/recovery.py** - 복구 관리자
  - 복구 플래그 파일 관리
  - AP 모드 크래시 복구

- [x] **database.py** - SQLite DB 관리
  - WAL 모드 설정 (`PRAGMA journal_mode=WAL`)
  - 동시성 처리 (`timeout=10, check_same_thread=False`)
  - 버전 기반 마이그레이션 (`schema_version` 테이블)
  - `photos` 테이블 (source, filename, google_id, title, 해상도, mime_type, taken_at, file_size, is_deleted, last_accessed)
  - `display_history` 테이블 (셔플 덱 사이클 추적)
  - `state` key-value 테이블
  - `last_displayed_photo_id` / `last_sync_token` 프로퍼티
  - `get_all_shown_photo_ids()` / `clear_display_history()` — 사이클 리셋
  - LRU 조회 (`get_lru_photos`), 소프트 삭제 (`mark_deleted`)
  - `google_id` 조건부 UNIQUE 인덱스

---

## Phase 2: WiFi & AP 모드 - 80% 완료

### 완료 ✅

- [x] **wifi/manager.py** - WiFi 연결 관리
  - nmcli 기반 연결/해제
  - 네트워크 스캔
  - 연결 상태 확인

- [x] **wifi/ap_mode.py** - AP 모드 매니저
  - NetworkManager hotspot 사용
  - ExecutionMode (DRY_RUN/PREVIEW/SAFE/NORMAL)
  - 타임아웃 워치독
  - nftables 포트 포워딩 (80→8000, 53→5300)
  - 복구 플래그 연동

- [x] **wifi/captive_portal.py** - DNS 서버
  - UDP DNS 서버
  - A 레코드 응답 (모든 도메인 → AP IP)
  - AAAA 쿼리 빈 응답

- [x] **button.py** - 물리 버튼 핸들러
  - gpiozero 기반 GPIO 입력 (GPIO 27)
  - 짧은 누름/길게 누름 콜백
  - 시뮬레이션 메서드

### 미완료 ❌

- [ ] **Captive Portal 팝업** (iOS/Android)
  - DNS 하이재킹은 동작하지만 자동 팝업이 안 뜸
  - 수동으로 10.42.0.1 접속은 가능
  - 우선순위: 낮음 (수동 접속으로 대체 가능)

---

## Phase 3: 웹 UI - 90% 완료

### 완료 ✅

- [x] **web/app.py** - FastAPI 앱
  - 라우터 마운트
  - 정적 파일 서빙
  - 템플릿 설정
  - 미들웨어 (요청 로깅, idle 타임아웃 리셋)

- [x] **web/routes.py** - API 라우트
  - `GET /api/status` - 시스템 상태 (배터리, WiFi, 상태머신)
  - `GET /api/settings` - 설정 조회
  - `PUT /api/settings` - 설정 변경 (schedule, photo_selection, display, image_processing, wifi, storage)
  - `GET /api/wifi/scan` - WiFi 스캔
  - `GET /api/wifi/status` - WiFi 상태
  - `POST /api/wifi/connect` - WiFi 연결
  - `GET /api/ap/status` - AP 상태
  - `POST /api/ap/start` - AP 시작
  - `POST /api/ap/stop` - AP 중지
  - `POST /api/system/apply` - 설정 적용 후 WiFi 연결
  - `POST /api/system/shutdown` - 종료
  - `POST /api/system/photo-update` - 사진 업데이트 실행
  - `GET /api/photos` - 사진 목록
  - `POST /api/photos/upload` - 사진 업로드 (스트리밍, 최대 20MB)
  - `DELETE /api/photos/{id}` - 사진 삭제
  - `GET /api/photos/{id}/thumbnail` - 썸네일
  - `GET /api/photos/{id}/original` - 원본 사진
  - `POST /api/photos/{id}/crop` - 사진 크롭
  - `POST /api/image-preview/random` - 랜덤 사진 미리보기
  - `POST /api/image-preview/process` - 이미지 처리 미리보기
  - Captive portal 감지 URL 응답

- [x] **web/templates/index.html** - 메인 UI
  - WiFi 설정 탭 (스캔, 연결, Apply & Connect)
  - 사진 갤러리 탭 (업로드, 썸네일 그리드, 삭제, 크롭)
  - 설정 탭 (스케줄 모드/시간, 사진 선택, 디스플레이 모델/회전, 이미지 처리 파라미터, 저장소 용량)
  - 시스템 탭 (상태 표시, 사진 업데이트, 종료)
  - 이미지 처리 미리보기 (실시간 파라미터 조정)

- [x] **web/templates/captive.html** - 캡티브 포털 랜딩
  - AP 접속 안내
  - 10.42.0.1 링크

### 미완료 ❌

- [ ] **Google Photos 연동 UI**
  - OAuth 인증 플로우
  - 앨범 선택

- [ ] **OTA 업데이트 UI**
  - 버전 확인
  - 업데이트 설치

---

## Phase 4: 사진 소스 - 75% 완료

### 완료 ✅

- [x] **photo_source/base.py** - 추상 기본 클래스
  - PhotoSource 인터페이스
  - Photo 데이터 클래스

- [x] **photo_source/local.py** - 로컬 파일시스템
  - photos/local/ 디렉토리 관리
  - 썸네일 생성 (.thumbnails/, 200x200)
  - 파일 업로드 처리
  - 지원 포맷: JPEG, PNG, HEIC (pillow-heif)

- [x] **photo_selector.py** - 사진 선택 로직
  - random 모드: 셔플 덱 (모든 사진을 한 번씩 보여준 후 사이클 리셋)
  - sequential 모드: added_at 기준 오름차순 (추가된 순)
  - 모든 사진이 표시되면 display_history 클리어 후 새 사이클 시작
  - 모든 소스 통합 선택 (local + 미래의 google 소스)

- [x] **frame_runner.py** - 사진 표시 루프
  - 소스 초기화 → 사진 선택 → 이미지 처리 → 디스플레이 출력 → DB 기록
  - `--dry-run` 모드: `debug_output.png`로 저장 (Mac 테스트용)

### 미완료 ❌

- [ ] **photo_source/google_photos.py** - Google Photos API
  - OAuth 2.0 인증
  - 앨범 메타데이터 동기화 (Delta Sync)
    - last_sync_token 관리
    - 증분 동기화 API 호출
  - 사진 다운로드
  - 용량 관리 (LRU 알고리즘 구현)
  - 삭제 여부 트래킹 (재다운로드 가능)
  - 다운로드 실패 시 로컬 사진 폴백

---

## Phase 5: 이미지 처리 - 100% 완료

### 완료 ✅

- [x] **image_processor.py** - 이미지 처리
  - 디스플레이 해상도 리사이즈
  - EXIF 기반 자동 회전
  - fit/fill 모드 (letterbox / crop)
  - 6색 Floyd-Steinberg 디더링
  - 조정 파라미터: brightness, contrast, saturation, gamma, sharpness, warmth
  - 배터리 아이콘 오버레이 (우측 상단)
    - 낮음 / 긴급 상태만 표시
    - PNG 아이콘 우선, 없으면 Pillow 직접 드로잉
  - 디스플레이 물리 회전 보정 (90/270도 시 캔버스 치환)
  - `from_config()` 클래스 메서드

---

## Phase 6: 디스플레이 드라이버 - 100% 완료

### 완료 ✅

- [x] **display/base.py** - 추상 기본 클래스
  - EinkDisplay 인터페이스 (width, height, color_mode)
  - init(), show(), clear(), sleep() 추상 메서드

- [x] **display/epd7in3e/** - 7.3" Spectra 6색 드라이버
  - `__init__.py` — Display7in3e 래퍼 (800×480, 지연 임포트로 Mac 호환)
  - `driver.py` — Waveshare EPD 드라이버 (spidev + gpiozero)
  - `config.py` — GPIO/SPI 설정

- [x] **display/epd13in3e/** - 13.3" Spectra 6색 드라이버
  - `__init__.py` — Display13in3e 래퍼 (1200×1600 네이티브, 지연 임포트로 Mac 호환)
  - `driver.py` — Waveshare EPD 드라이버 (Dual CS: CS_M 왼쪽 600px, CS_S 오른쪽 600px)
  - `config.py` — GPIO/SPI 설정 (.so C 공유 라이브러리 기반, Pi5 자동 감지)
  - `DEV_Config_*.so` — Waveshare C 라이브러리 (32/64bit, Pi4/Pi5 각 버전)

---

## Phase 7: 전원 관리 - 100% 완료

### 완료 ✅

- [x] **power_manager.py** - Witty Pi 연동
  - I2C 통신 (주소 0x08, Firmware ID 0x37 = L3V7)
  - 배터리 전압/전류/출력전압 읽기 (레지스터 1~6)
  - 배터리 % 추정 (선형 보간, 3.0V~4.2V)
  - 저전압 임계값 설정 (레지스터 19)
  - 부팅 알람 설정 (Alarm 1, 레지스터 27~30, BCD 인코딩)
    - `schedule.update_time` + `schedule.timezone` → UTC 변환 후 설정
    - `_ALARM_DAY_EVERY_DAY = 0x80` (매일 반복)
  - Graceful Shutdown: 알람 설정 → DB에 배터리 전압 저장 → systemctl poweroff
  - Mac/dry-run 자동 폴백 (smbus2 없거나 Linux 아닌 환경)

---

## Phase 8: 상태머신 - 100% 완료

### 완료 ✅

- [x] **state_machine.py** - 상태머신 구현
  - States: INIT, WIFI_CONNECT, WEB_UI_MODE, AP_MODE, PHOTO_UPDATE, SCHEDULE, SHUTDOWN, ERROR
  - Events: INIT_COMPLETE, WIFI_SUCCESS, WIFI_SUCCESS_WEB_UI, WIFI_FAIL, AP_TIMEOUT, WEB_UI_TIMEOUT, PHOTO_DONE, PHOTO_FAIL, SHUTDOWN_REQUEST, PHOTO_UPDATE_REQUEST, ERROR_OCCURRED
  - 이벤트 큐 (thread-safe queue.Queue)
  - 상태 전이 로직 (핸들러: `_on_<state>`)
  - 스레드 아키텍처: 메인 스레드(상태머신) + 웹 스레드(FastAPI)
  - `_web_ui_requested` 플래그: 부팅 시 버튼 눌림 감지 → WiFi 성공 시 WEB_UI_MODE 분기
  - WEB_UI_MODE: WiFi 연결 유지, 포트 8080, 타임아웃 처리
  - AP_MODE: ap_manager 연동, 포트 80, AP_TIMEOUT 처리
  - SCHEDULE → SHUTDOWN: power_manager.schedule_and_shutdown() 호출
  - platform.system() != "Linux" 자동 dry_run
  - mode_info 프로퍼티 (웹 API 상태 노출용)

- [x] **버튼 재누름 이벤트 연결** (AP_MODE/WEB_UI_MODE 중)
  - _setup_button_for_exit() / _clear_button_callback() 헬퍼
  - AP_MODE 진입 시 재누름 → AP_TIMEOUT 이벤트 포스팅
  - WEB_UI_MODE 진입 시 재누름 → WEB_UI_TIMEOUT 이벤트 포스팅
  - 모드 종료 시 콜백 클리어

- [x] **이전 사진 복원 로직 (구조)**
  - _restore_last_photo() 헬퍼: DB last_displayed_photo_id 조회
  - AP_TIMEOUT / WEB_UI_TIMEOUT 종료 경로에서 호출
  - 실제 디스플레이 출력은 status_display.py 구현 이후 연동

- [x] **ERROR → AP_MODE 복구 경로**
  - _enter_error() → _enter_ap_mode() 로 변경 완료

### 미완료 ❌

- [ ] **status_display.py** - E-ink 상태 표시
  - AP 모드 안내 화면 (SSID, IP, 접속 방법 텍스트)
  - **WEB_UI_MODE 안내 화면** (Pi WiFi IP 주소, 포트 8080, 같은 WiFi 연결 안내)
  - 에러 메시지 표시
    - 에러 타입별: 네트워크 오류, Google API 오류, 저장소 부족 등
  - 배터리 부족 표시
  - 업데이트 완료 표시 (선택)
  - 디폴트 이미지 로드 및 표시 로직

---

## Phase 9: OTA 업데이트 - 0% 완료

### 미완료 ❌

- [ ] **ota/version.py** - 버전 관리
  - 현재 버전 읽기
  - 버전 비교

- [ ] **ota/updater.py** - 업데이트 다운로드/설치
  - GitHub Release API
  - 다운로드 및 설치
  - 롤백 기능
    - 백업 대상: src/, config/ 등
    - 롤백 프로세스 정의
  - 부팅 시 자동 확인 옵션 (auto_check)
  - 업데이트 전 백업 (backup_before_update)

---

## Phase 10: 에셋 및 스크립트 - 60% 완료

### 완료 ✅

- [x] **assets/icons/battery_low.png** - 38×20px RGBA, 주황 배터리 아이콘
- [x] **assets/icons/battery_critical.png** - 38×20px RGBA, 빨간 X 배터리 아이콘
- [x] **scripts/install_service.sh** - 시스템 패키지, venv, 의존성, systemd 서비스 자동 설치
- [x] **scripts/install_recovery.sh** - AP 복구 서비스 설치
- [x] **scripts/ap_recovery.sh** - AP 모드 크래시 복구 스크립트
- [x] **scripts/preview_web.py** - 웹 UI 개발 프리뷰 서버

### 미완료 ❌

- [ ] **assets/default.png** - 종료 시 표시할 디폴트 이미지 (전원 꺼질 때)

---

## Phase 11: 저장소 및 로깅 - 0% 완료

### 미완료 ❌

- [ ] **저장소 용량 관리**
  - Google Photos 최대 용량 제한 (기본 1000MB)
  - 로컬 업로드 최대 용량 제한 (기본 1000MB)
  - 용량 초과 시 LRU 삭제
  - 미리 선정할 사진 수 (prefetch_count)

- [ ] **로그 로테이션**
  - 로그 파일 위치: logs/einkframe.log
  - 최대 5개 파일, 각 1MB
  - Python logging.handlers.RotatingFileHandler 사용

---

## Phase 12: 통합 및 테스트 - 30% 완료

### 완료 ✅

- [x] test_database.py — DB 작업, 마이그레이션, 사진 관리
- [x] test_local_photo_source.py — LocalPhotoSource 파일 동기화, 업로드
- [x] test_processor_visual.py — 이미지 처리 출력 검증
- [x] test_state_machine.py — 상태 전이, 이벤트 처리

### 미완료 ❌

- [ ] 전체 부팅 시퀀스 테스트
- [ ] AP 모드 → WiFi 전환 테스트
- [ ] 배터리 부족 시나리오 테스트
- [ ] 에러 복구 테스트
- [ ] OTA 업데이트 테스트

---

## 다음 구현 순서 (권장)

### 높음 (핵심)
1. **status_display.py** — E-ink 상태 화면 (AP/WEB_UI 모드 안내)
2. **photo_source/google_photos.py** — Google Photos OAuth + Delta Sync

### 중간 (완성도)
3. **assets/default.png** — 종료 시 화면
4. **저장소 용량 관리** — LRU 삭제 로직
5. **로그 로테이션** — RotatingFileHandler 설정

### 낮음 (선택)
6. **OTA 업데이트**
7. **Captive Portal 팝업 수정**

---

## Mac에서 개발 가능한 것

- image_processor.py ✅
- photo_source/local.py ✅
- 웹 UI (갤러리, 설정, 크롭, 이미지 프리뷰) ✅
- photo_source/google_photos.py
- state_machine.py (DRY_RUN 모드) ✅
- OTA 버전 비교 로직

Pi 필요:
- display 드라이버 (하드웨어 SPI)
- power_manager.py (I2C)
- 전체 통합 테스트

---

*마지막 업데이트: 2026-03-15*
