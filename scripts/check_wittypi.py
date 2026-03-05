#!/usr/bin/env python3
"""Witty Pi 4 L3V7 상태 진단 스크립트.

Pi 시스템 시간, Witty Pi RTC 시간, 예약된 켜짐/꺼짐 알람을 출력합니다.
"""

import subprocess
from datetime import datetime, timezone

try:
    import smbus2
except ImportError:
    print("ERROR: smbus2 not installed. Run: pip install smbus2")
    raise SystemExit(1)

ADDR = 0x08
BUS  = 1


def from_bcd(v: int) -> int:
    return ((v >> 4) * 10) + (v & 0x0F)


def read(bus, reg: int) -> int:
    return bus.read_byte_data(ADDR, reg)


def fmt_time(h, m, s) -> str:
    return f"{h:02d}:{m:02d}:{s:02d}"


bus = smbus2.SMBus(BUS)

# ── Pi 시스템 시간 ────────────────────────────────────────────────────────────
now_utc = datetime.now(timezone.utc)
result  = subprocess.run(
    ["date", "+%Y-%m-%d %H:%M:%S %Z"],
    capture_output=True, text=True,
)
pi_local = result.stdout.strip()

print("=" * 52)
print("  Witty Pi 4 L3V7 상태 진단")
print("=" * 52)
print(f"\n[Pi 시스템 시간]")
print(f"  UTC   : {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  Local : {pi_local}")

# ── PCF85063A Control 레지스터 ────────────────────────────────────────────────
try:
    ctrl1_raw = read(bus, 54)
    ctrl2_raw = read(bus, 55)
    stop_bit  = bool(ctrl1_raw & 0x20)   # bit5: STOP (1=RTC 멈춤)
    aie_bit   = bool(ctrl2_raw & 0x80)   # bit7: AIE (알람 인터럽트 활성)
    af_bit    = bool(ctrl2_raw & 0x40)   # bit6: AF (알람 발화됨)

    print(f"\n[PCF85063A 상태]")
    stop_str = "🔴 멈춤 (STOP=1)" if stop_bit else "🟢 동작중 (STOP=0)"
    print(f"  Control_1 (54) : raw=0x{ctrl1_raw:02X}  STOP={int(stop_bit)} → {stop_str}")
    print(f"  Control_2 (55) : raw=0x{ctrl2_raw:02X}  AIE={int(aie_bit)}  AF={int(af_bit)}")
    if aie_bit:
        print(f"  ⚠️  AIE=1: 알람 인터럽트 활성화됨 (ATtiny가 발화 2초 전에 설정한 값)")
except OSError as e:
    print(f"\n[PCF85063A 상태]  ERROR: {e}")

# ── Witty Pi RTC ──────────────────────────────────────────────────────────────
rtc_year = rtc_mon = rtc_day = rtc_hour = rtc_min = rtc_sec = 0
try:
    sec_raw     = read(bus, 58)
    os_bit      = bool(sec_raw & 0x80)   # bit7: OS (Oscillator Stop)
    rtc_sec     = from_bcd(sec_raw & 0x7F)
    rtc_min     = from_bcd(read(bus, 59))
    rtc_hour    = from_bcd(read(bus, 60))
    rtc_day     = from_bcd(read(bus, 61))
    rtc_weekday = from_bcd(read(bus, 62))  # 1=월 … 7=일
    rtc_mon     = from_bcd(read(bus, 63))
    rtc_year    = from_bcd(read(bus, 64))

    _DOW = {1:"월", 2:"화", 3:"수", 4:"목", 5:"금", 6:"토", 7:"일"}
    rtc_str = (
        f"20{rtc_year:02d}-{rtc_mon:02d}-{rtc_day:02d}"
        f"({_DOW.get(rtc_weekday,'?')}) "
        f"{fmt_time(rtc_hour, rtc_min, rtc_sec)} UTC"
    )
    drift_s = int((now_utc - datetime(
        2000 + rtc_year, max(rtc_mon, 1), max(rtc_day, 1),
        rtc_hour, rtc_min, rtc_sec, tzinfo=timezone.utc
    )).total_seconds()) if rtc_mon > 0 and rtc_day > 0 else None

    print(f"\n[Witty Pi RTC]")
    if os_bit:
        print(f"  ⚠️  OS=1: 오실레이터 정지 감지 (전원 차단됐었음 — sync_rtc() 필요)")
    print(f"  RTC   : {rtc_str}")
    if drift_s is not None:
        print(f"  오차  : {drift_s:+d}초 (Pi 기준)")
    else:
        print(f"  오차  : 계산 불가 (월/일이 0)")

except OSError as e:
    print(f"\n[Witty Pi RTC]  ERROR: {e}")

# ── 알람 1 (켜짐) ─────────────────────────────────────────────────────────────
try:
    a1_sec     = from_bcd(read(bus, 27))
    a1_min     = from_bcd(read(bus, 28))
    a1_hour    = from_bcd(read(bus, 29))
    a1_day_raw = read(bus, 30)
    a1_day     = from_bcd(a1_day_raw)
    a1_wd_raw  = read(bus, 31)

    print(f"\n[알람 1 — 켜짐 예약]")
    print(f"  시간  : {fmt_time(a1_hour, a1_min, a1_sec)} UTC")
    print(f"  날짜  : {a1_day}일  raw=0x{a1_day_raw:02X}")
    print(f"  요일  : raw=0x{a1_wd_raw:02X}  (ATtiny 전용 — 우리 코드가 쓰지 않음)")

    if rtc_mon > 0 and rtc_day > 0 and a1_day > 0:
        # 알람 날짜가 이번 달 기준으로 오늘 이후인지 계산
        alarm_dt = datetime(
            2000 + rtc_year, rtc_mon, a1_day,
            a1_hour, a1_min, a1_sec, tzinfo=timezone.utc
        )
        rtc_now = datetime(
            2000 + rtc_year, rtc_mon, rtc_day,
            rtc_hour, rtc_min, rtc_sec, tzinfo=timezone.utc
        )
        diff = int((alarm_dt - rtc_now).total_seconds())
        if diff > 0:
            h, rem = divmod(diff, 3600)
            m, s   = divmod(rem, 60)
            print(f"  남은  : {h}시간 {m}분 {s}초 후 (RTC 기준)")
        else:
            h, rem = divmod(-diff, 3600)
            m, s   = divmod(rem, 60)
            print(f"  상태  : 알람 이미 지남 ({h}시간 {m}분 {s}초 전)")
    elif a1_day == 0:
        print(f"  ⚠️  날짜=0: 알람 미설정 상태")

except OSError as e:
    print(f"\n[알람 1 — 켜짐 예약]  ERROR: {e}")

# ── 알람 2 (꺼짐) ─────────────────────────────────────────────────────────────
try:
    a2_sec     = from_bcd(read(bus, 32))
    a2_min     = from_bcd(read(bus, 33))
    a2_hour    = from_bcd(read(bus, 34))
    a2_day_raw = read(bus, 35)
    a2_day     = from_bcd(a2_day_raw)

    print(f"\n[알람 2 — 꺼짐 예약]")
    if a2_hour == 0 and a2_min == 0 and a2_sec == 0 and a2_day == 0:
        print(f"  (설정 없음)")
    else:
        print(f"  시간  : {fmt_time(a2_hour, a2_min, a2_sec)} UTC")
        print(f"  날짜  : {a2_day}일  raw=0x{a2_day_raw:02X}")

except OSError as e:
    print(f"\n[알람 2 — 꺼짐 예약]  ERROR: {e}")

print("\n" + "=" * 52)
