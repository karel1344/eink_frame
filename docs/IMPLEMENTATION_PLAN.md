# E-Ink Photo Frame 구현 계획

## 현재 상태 요약

| 카테고리 | 구현율 |
|----------|--------|
| 인프라/설정 | 100% |
| WiFi/AP 모드 | 80% |
| 웹 UI | 70% |
| 사진 소스 | 60% |
| 이미지 처리 | 100% |
| 디스플레이 드라이버 | 100% |
| 전원 관리 | 0% |
| 상태머신 | 0% |
| OTA 업데이트 | 0% |
| 에셋/스크립트 | 50% |
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
  - 플래그 없으면 프로덕션 모드

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
  - `display_history` 테이블 (반복 방지용, 최근 30장)
  - `state` key-value 테이블
  - `last_displayed_photo_id` / `last_sync_token` 프로퍼티
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
  - gpiozero 기반 GPIO 입력
  - 짧은 누름/길게 누름 콜백
  - 시뮬레이션 메서드

### 미완료 ❌

- [ ] **Captive Portal 팝업** (iOS/Android)
  - DNS 하이재킹은 동작하지만 자동 팝업이 안 뜸
  - 수동으로 10.42.0.1 접속은 가능
  - 우선순위: 낮음 (수동 접속으로 대체 가능)

---

## Phase 3: 웹 UI - 70% 완료

### 완료 ✅

- [x] **web/app.py** - FastAPI 앱
  - 라우터 마운트
  - 정적 파일 서빙
  - 템플릿 설정

- [x] **web/routes.py** - API 라우트
  - `GET /api/status` - 시스템 상태 (스텁)
  - `GET /api/settings` - 설정 조회
  - `PUT /api/settings` - 설정 변경 (schedule, photo_selection, display, image_processing, battery, wifi)
  - `GET /api/wifi/scan` - WiFi 스캔
  - `GET /api/wifi/status` - WiFi 상태
  - `POST /api/wifi/connect` - WiFi 연결
  - `GET /api/ap/status` - AP 상태
  - `POST /api/ap/start` - AP 시작
  - `POST /api/ap/stop` - AP 중지
  - `POST /api/system/apply` - 설정 적용 후 WiFi 연결
  - `POST /api/system/shutdown` - 종료 (스텁)
  - `GET /api/photos` - 사진 목록
  - `POST /api/photos/upload` - 사진 업로드
  - `DELETE /api/photos/{id}` - 사진 삭제
  - `GET /api/photos/{id}/thumbnail` - 썸네일
  - Captive portal 감지 URL 응답

- [x] **web/templates/index.html** - 메인 UI
  - WiFi 설정 탭 (스캔, 연결, Apply & Connect)
  - 사진 갤러리 탭 (업로드, 썸네일 그리드, 삭제)
  - 설정 탭 (스케줄, 사진 선택, 디스플레이, 배터리)

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

## Phase 4: 사진 소스 - 60% 완료

### 완료 ✅

- [x] **photo_source/base.py** - 추상 기본 클래스
  - PhotoSource 인터페이스
  - Photo 데이터 클래스

- [x] **photo_source/local.py** - 로컬 파일시스템
  - photos/local/ 디렉토리 관리
  - 썸네일 생성 (.thumbnails/, 200x200)
  - 파일 업로드 처리
  - 지원 포맷: JPEG, PNG, HEIC (pillow-heif)

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

- [ ] **사진 선택 로직**
  - 순차/랜덤/날짜 기반 선택
  - 반복 방지 (최근 N장, 기본 30장)
  - 로컬 + Google 통합 선택

---

## Phase 5: 이미지 처리 - 100% 완료

### 완료 ✅

- [x] **image_processor.py** - 이미지 처리
  - 디스플레이 해상도 리사이즈
  - EXIF 기반 자동 회전
  - fit/fill 모드 (letterbox / crop)
  - 배터리 아이콘 오버레이 (우측 상단)
    - 낮음(3.0~3.3V) / 긴급(<3.0V) 상태만 표시
    - PNG 아이콘 우선, 없으면 Pillow 직접 드로잉
  - 디스플레이 물리 회전 보정 (90/270도 시 캔버스 치환)
  - `from_config()` 클래스 메서드

---

## Phase 6: 디스플레이 드라이버 - 100% 완료

### 완료 ✅

- [x] **display/base.py** - 추상 기본 클래스
  - EinkDisplay 인터페이스 (width, height, color_mode)
  - init(), show(), clear(), sleep() 추상 메서드

- [x] **display/display_7in3e.py** - 7.3" 6색 드라이버 래퍼
  - 800×480 해상도
  - 지연 임포트 (Mac 호환)

- [x] **display/display_13in3k.py** - 13.3" 4단계 회색 드라이버 래퍼
  - 960×680 해상도
  - 4GRAY 모드 (init_4GRAY, display_4Gray)

- [x] **display/epd7in3e.py, epd13in3k.py, epdconfig.py** - Waveshare 공식 드라이버

---

## Phase 7: 전원 관리 - 0% 완료

### 미완료 ❌

- [ ] **power_manager.py** - Witty Pi 연동
  - I2C 통신 (주소 0x69, 배터리 레지스터)
  - 배터리 전압 읽기
    - 저전압 임계값: 3.3V (경고)
    - 긴급 종료 임계값: 3.0V
  - 다음 부팅 스케줄 설정 (schedule.update_time 사용)
  - Graceful Shutdown 시퀀스
    - Witty Pi 스케줄 설정 → systemctl poweroff

---

## Phase 8: 상태머신 - 0% 완료

### 미완료 ❌

- [ ] **state_machine.py** - 상태머신 구현
  - States: INIT, WIFI_CONNECT, AP_MODE, PHOTO_UPDATE, SCHEDULE, SHUTDOWN, ERROR
  - Events: INIT_COMPLETE, BUTTON_PRESSED, WIFI_SUCCESS, WIFI_FAIL, etc.
  - 이벤트 큐 (thread-safe queue.Queue)
  - 상태 전이 로직
  - 스레드 아키텍처: 메인 스레드(상태머신) + 웹 스레드(FastAPI)
  - INIT 내부 단계: 하드웨어 초기화 → 설정 로드 → 배터리 확인 → DB 연결 → 오프라인 모드 확인
  - AP 모드 버튼 재누름 감지 (AP_BUTTON_EXIT 이벤트)
  - AP 모드 타임아웃 워치독 (web_ui.timeout 설정값 사용)
  - AP 모드 종료 시 이전 사진 복원/디폴트 이미지 표시 로직
  - Watchdog 타이머 (무한루프 방지, systemd watchdog 또는 별도 타이머)
  - 메모리 관리: AP 모드 종료 후 이미지 처리 시작 (동시 실행 방지)

- [ ] **status_display.py** - E-ink 상태 표시
  - AP 모드 안내 화면 (SSID, IP, 접속 방법 텍스트)
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

## Phase 10: 에셋 및 스크립트 - 50% 완료

### 완료 ✅

- [x] **assets/icons/battery_low.png** - 38×20px RGBA, 주황 배터리 아이콘
- [x] **assets/icons/battery_critical.png** - 38×20px RGBA, 빨간 X 배터리 아이콘
- [x] **scripts/install_service.sh** - systemd 서비스 동적 생성 및 설치
- [x] **scripts/install.sh** - 전체 설치 스크립트
- [x] **scripts/setup_wittypi.sh** - Witty Pi 설정 스크립트

### 미완료 ❌

- [ ] **assets/default.png** - 종료 시 표시할 디폴트 이미지 (전원 꺼질 때)
- [ ] **scripts/wittypi_schedule.sh** - Witty Pi 스케줄 설정 (런타임 호출용)

---

## Phase 11: 저장소 및 로깅 - 0% 완료

### 미완료 ❌

- [ ] **저장소 용량 관리**
  - Google Photos 최대 용량 제한 (기본 500MB)
  - 로컬 업로드 최대 용량 제한 (기본 500MB)
  - 용량 초과 시 LRU 삭제
  - 미리 선정할 사진 수 (prefetch_count)

- [ ] **로그 로테이션**
  - 로그 파일 위치: logs/einkframe.log
  - 최대 5개 파일, 각 1MB
  - Python logging.handlers.RotatingFileHandler 사용

---

## Phase 12: 통합 및 테스트 - 0% 완료

### 미완료 ❌

- [ ] 전체 부팅 시퀀스 테스트
- [ ] AP 모드 → WiFi 전환 테스트
- [ ] 사진 업데이트 플로우 테스트
- [ ] 배터리 부족 시나리오 테스트
- [ ] 에러 복구 테스트
- [ ] OTA 업데이트 테스트

---

## 다음 구현 순서 (권장)

### 높음 (핵심)
1. ~~**웹 UI 설정 탭**~~ → **진행 중**
2. **사진 표시 루프** — 사진 선택 → ImageProcessor → 디스플레이 출력 → 종료
3. **power_manager.py** — Witty Pi 배터리/스케줄
4. **state_machine.py** — 전체 흐름 제어

### 중간 (완성도)
5. **photo_source/google_photos.py** — Google Photos
6. **status_display.py** — E-ink 상태 화면
7. **assets/default.png** — 종료 시 화면

### 낮음 (선택)
8. **OTA 업데이트**
9. **Captive Portal 팝업 수정**
10. **로그 로테이션**

---

## Mac에서 개발 가능한 것

- image_processor.py ✅
- photo_source/local.py ✅
- 웹 UI (갤러리, 설정) ← 지금 여기
- photo_source/google_photos.py
- state_machine.py (DRY_RUN 모드)
- OTA 버전 비교 로직

Pi 필요:
- display 드라이버 (하드웨어 SPI)
- power_manager.py (I2C)
- Witty Pi 스케줄 스크립트
- 전체 통합 테스트

---

*마지막 업데이트: 2026-03-04 (image_processor, display 드라이버, 배터리 아이콘 구현 완료 / 설정 UI 진행 중)*
