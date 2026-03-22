# KSPD OSINT Engine — 전체 파일 업데이트 프롬프트

## 작업 지시

`C:\work\kspd-osint-py\kspd-osint-py\` 프로젝트의 아래 6개 파일을 **아래 코드 블록의 내용으로 정확히 덮어쓰기** 해주세요.

기존 파일을 수정하지 말고, 각 파일의 전체 내용을 아래 코드로 교체하세요.

**주의사항:**
- `config/settings.py`의 `FIRMS_MAP_KEY`는 현재 PC에 이미 입력된 키가 있을 수 있습니다. 덮어쓴 후 기존 키를 다시 입력하세요.
- 나머지 API 키(AISStream, OpenSky, ACLED, Gemini)는 이미 포함되어 있습니다.

---

## 변경 사항 요약

| 파일 | 변경 내용 |
|------|----------|
| `config/settings.py` | 변경 없음 (API 키 유지) |
| `collectors/aviation.py` | 군용기 필터 대폭 완화: 군사 키워드 30개 추가, NATO 스쿼크 대역(0100~0777), 고고도 기준 10000m+대상국 확대, 카테고리 4+, 콜사인 없는 고고도기 포함, 지역별 로그 출력 |
| `collectors/maritime.py` | 군함 필터 대폭 완화: 정부선박(51~55), 선박명/콜사인 키워드(NAVY/PATROL/USS 등), 목적지 군항 탐지, 80m/18kts 기준, 지역별 로그 출력 |
| `collectors/conflicts.py` | GDELT 쿼리 단순화+타임아웃 시 즉시 건너뜀+연속3회 실패 중단+Session 재사용, ACLED 첫 403에서 즉시 전체 건너뜀(유료 라이선스 안내) |
| `collectors/thermal.py` | 변경 없음 (정상 작동 확인됨) |
| `main.py` | Gemini 모델 `2.5-flash`, 타임아웃 120초, 브리핑 제목에 실제 날짜, 열점 통계+지역별 열점+maritime 스캔 수를 Gemini에 전달, auto_briefing 열점 표시 개선 |

---

## 파일 1: `config/settings.py`

```python
"""
KSPD OSINT Engine — 설정 파일
API 키, 감시 대상, 알림 기준 정의

※ 실제 운용 시 이 파일을 .env 또는 환경변수로 분리 권장
"""

# ══════════════════════════════════════════════════
# API CREDENTIALS
# ══════════════════════════════════════════════════

# AISStream.io (무료)
AISSTREAM_API_KEY = "df9d1b6c28bbbf1028cca940c3f984b97fdff96e"

# OpenSky Network (무료, Basic Auth)
OPENSKY_CLIENT_ID = "antonio.yhp@gmail.com-api-client"
OPENSKY_CLIENT_SECRET = "6nBw3zYyMzVjIHuBcF4Nhx7UOLxGcmG0"

# ACLED (myACLED 계정 이메일/비밀번호로 OAuth 토큰 발급)
# https://acleddata.com/user/register 에서 가입 후 아래 입력
ACLED_EMAIL = "ceo@helios-intel.com"
ACLED_PASSWORD = "theone132!Q"

# Gemini API (기존 사용중인 키)
GEMINI_API_KEY = "AIzaSyAR2BHMPSI6aa-CEtLSHzyK0LDVAXOyfOU"

# NASA FIRMS (선택, 없어도 기본 접근 가능)
FIRMS_MAP_KEY = ""     # ※ PC에서 이미 입력한 키를 여기에도 넣으세요


# ══════════════════════════════════════════════════
# 감시 지역 (Bounding Box: [[남서위도, 남서경도], [북동위도, 북동경도]])
# ══════════════════════════════════════════════════

WATCH_REGIONS = {
    # ── 중동 전구 ──
    "hormuz": {
        "name": "호르무즈 해협", "nameEn": "Strait of Hormuz",
        "bbox": [[24.0, 54.0], [27.5, 58.0]],
        "theater": "middleEast", "priority": "HIGH"
    },
    "persian_gulf": {
        "name": "페르시아만", "nameEn": "Persian Gulf",
        "bbox": [[24.0, 48.0], [30.5, 56.5]],
        "theater": "middleEast", "priority": "HIGH"
    },
    "red_sea": {
        "name": "홍해", "nameEn": "Red Sea",
        "bbox": [[12.0, 41.0], [20.0, 45.0]],
        "theater": "middleEast", "priority": "HIGH"
    },
    "east_med": {
        "name": "동부 지중해", "nameEn": "Eastern Mediterranean",
        "bbox": [[31.0, 28.0], [37.0, 36.0]],
        "theater": "middleEast", "priority": "MEDIUM"
    },

    # ── 인도태평양 전구 ──
    "taiwan_strait": {
        "name": "대만 해협", "nameEn": "Taiwan Strait",
        "bbox": [[22.5, 117.0], [26.0, 121.0]],
        "theater": "indoPacific", "priority": "HIGH"
    },
    "south_china_sea": {
        "name": "남중국해", "nameEn": "South China Sea",
        "bbox": [[5.0, 108.0], [18.0, 120.0]],
        "theater": "indoPacific", "priority": "HIGH"
    },
    "korean_peninsula": {
        "name": "한반도 주변", "nameEn": "Korean Peninsula",
        "bbox": [[33.0, 124.0], [40.0, 132.0]],
        "theater": "indoPacific", "priority": "MEDIUM"
    },

    # ── 유럽 전구 ──
    "black_sea": {
        "name": "흑해", "nameEn": "Black Sea",
        "bbox": [[40.5, 27.5], [47.0, 42.0]],
        "theater": "europe", "priority": "HIGH"
    },
    "baltic_sea": {
        "name": "발트해", "nameEn": "Baltic Sea",
        "bbox": [[53.0, 13.0], [60.0, 30.0]],
        "theater": "europe", "priority": "ELEVATED"
    },
}

# ══════════════════════════════════════════════════
# 군용기 콜사인 패턴 (정규식)
# ══════════════════════════════════════════════════
import re

MILITARY_CALLSIGN_PATTERNS = [
    re.compile(r'^RCH\d'),      # AMC 수송기
    re.compile(r'^REACH\d'),    # AMC 수송기
    re.compile(r'^DUKE\d'),     # 급유기
    re.compile(r'^ETHYL\d'),    # 급유기
    re.compile(r'^IRON\d'),     # 급유기/수송기
    re.compile(r'^DOOM\d'),     # B-52
    re.compile(r'^BONE\d'),     # B-1B
    re.compile(r'^REAPER\d'),   # MQ-9
    re.compile(r'^HAWK\d'),     # RQ-4
    re.compile(r'^FORTE\d'),    # RQ-4 유럽
    re.compile(r'^JAKE\d'),     # P-8A
    re.compile(r'^COBRA\d'),    # 특수작전
    re.compile(r'^NAVY\d'),     # 미 해군
    re.compile(r'^NATO\d'),     # NATO
    re.compile(r'^RAF\d'),      # 영국 공군
    re.compile(r'^GAF\d'),      # 독일 공군
    re.compile(r'^LAGR\d'),     # 미 육군
    re.compile(r'^PUMA\d'),     # 특수작전
    re.compile(r'^TOPCAT\d'),   # E-2 Hawkeye
    re.compile(r'^SENTRY\d'),   # E-3 AWACS
]

# ══════════════════════════════════════════════════
# 알려진 군함 MMSI (공개 데이터 기반)
# ══════════════════════════════════════════════════
KNOWN_NAVAL_MMSI = {
    "369970415": {"name": "USS Abraham Lincoln (CVN-72)", "type": "carrier", "nation": "US"},
    "369970390": {"name": "USS Eisenhower (CVN-69)", "type": "carrier", "nation": "US"},
    "369970430": {"name": "USS Gerald R. Ford (CVN-78)", "type": "carrier", "nation": "US"},
    "369970420": {"name": "USS Theodore Roosevelt (CVN-71)", "type": "carrier", "nation": "US"},
}

# 군사 시설 좌표 (열 이상 탐지용)
MILITARY_FACILITIES = [
    {"name": "나탄즈 핵시설 (이란)", "lat": 33.72, "lon": 51.73, "radius_km": 20},
    {"name": "이스판 핵시설 (이란)", "lat": 32.65, "lon": 51.68, "radius_km": 15},
    {"name": "부셰르 원전 (이란)", "lat": 28.83, "lon": 50.89, "radius_km": 10},
    {"name": "반다르아바스 해군기지", "lat": 27.15, "lon": 56.28, "radius_km": 15},
    {"name": "디모나 핵시설 (이스라엘)", "lat": 31.00, "lon": 35.14, "radius_km": 10},
    {"name": "영변 핵시설 (북한)", "lat": 39.79, "lon": 125.75, "radius_km": 10},
    {"name": "세바스토폴 해군기지", "lat": 44.62, "lon": 33.53, "radius_km": 15},
    {"name": "유린 기지 (하이난)", "lat": 18.25, "lon": 109.55, "radius_km": 20},
]

# ACLED 감시 국가
WATCH_COUNTRIES = {
    "middleEast": ["Iran", "Iraq", "Syria", "Yemen", "Lebanon", "Israel", "Palestine",
                   "Saudi Arabia", "United Arab Emirates"],
    "indoPacific": ["China", "Taiwan", "Philippines", "South Korea", "North Korea",
                    "Japan", "Myanmar"],
    "europe": ["Ukraine", "Russia", "Poland", "Romania", "Moldova", "Belarus"],
    "africa": ["Sudan", "Libya", "Somalia", "Ethiopia", "Democratic Republic of Congo"]
}
```

---

## 파일 2: `collectors/aviation.py`

```python
"""
KSPD OSINT Engine — 군용기 수집기 (OpenSky Network)
OpenSky REST API로 감시 지역별 항공기 데이터 수집 → 군용기 필터링
"""

import requests
import json
import time
import os
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET,
    WATCH_REGIONS, MILITARY_CALLSIGN_PATTERNS
)

OPENSKY_BASE = "https://opensky-network.org/api"


def fetch_region(region_key, region):
    """OpenSky API로 특정 지역 항공기 데이터 수집"""
    (lat_min, lon_min), (lat_max, lon_max) = region["bbox"]
    url = f"{OPENSKY_BASE}/states/all"
    params = {
        "lamin": lat_min, "lomin": lon_min,
        "lamax": lat_max, "lomax": lon_max
    }

    auth = None
    if OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET:
        auth = (OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)

    try:
        resp = requests.get(url, params=params, auth=auth, timeout=30)
        if resp.status_code == 429:
            print(f"  [Rate Limit] {region_key} — 10초 대기 후 재시도")
            time.sleep(12)
            resp = requests.get(url, params=params, auth=auth, timeout=30)

        if resp.status_code != 200:
            print(f"  [Error] {region_key}: HTTP {resp.status_code}")
            return None

        data = resp.json()
        states = data.get("states", [])

        aircraft = []
        for s in states:
            aircraft.append({
                "icao24": s[0],
                "callsign": (s[1] or "").strip(),
                "origin_country": s[2],
                "latitude": s[6],
                "longitude": s[5],
                "altitude_m": s[7],
                "on_ground": s[8],
                "velocity_ms": s[9],
                "heading": s[10],
                "squawk": s[14],
                "category": s[17] if len(s) > 17 else None,
            })

        return {
            "region": region_key,
            "regionName": region["name"],
            "theater": region["theater"],
            "timestamp": data.get("time"),
            "total_aircraft": len(aircraft),
            "aircraft": aircraft
        }

    except Exception as e:
        print(f"  [Error] {region_key}: {e}")
        return None


def is_military(ac):
    """군용기 판별 (완화된 필터)"""
    callsign = (ac.get("callsign") or "").upper()
    country = ac.get("origin_country", "")

    # 1. 콜사인 패턴 매칭
    for pattern in MILITARY_CALLSIGN_PATTERNS:
        if pattern.search(callsign):
            return True

    # 2. 군 관련 콜사인 키워드 (패턴 외 추가)
    MIL_KEYWORDS = ("MIL", "FORCE", "ARMY", "GUARD", "AWACS", "TANKER",
                    "SIGINT", "ELINT", "MAGIC", "ATLAS", "GIANT", "COMET",
                    "SPEED", "VIPER", "EAGLE", "FURY", "SWORD", "LANCE",
                    "TANGO", "ALPHA", "BRAVO", "VADER", "HAVOC", "CHAOS",
                    "STORM", "THUD", "TOPGUN", "TALON", "STEEL")
    if callsign and any(kw in callsign for kw in MIL_KEYWORDS):
        return True

    # 3. 비상 스쿼크
    if ac.get("squawk") in ("7500", "7600", "7700"):
        return True

    # 4. 군용 스쿼크 대역 (NATO: 01xx~07xx)
    sq = ac.get("squawk") or ""
    if sq and sq.isdigit():
        sq_int = int(sq)
        if 100 <= sq_int <= 777:  # NATO military squawk range
            return True

    # 5. 고고도 비상업용 (ISR/정찰 가능성)
    alt = ac.get("altitude_m")
    vel = ac.get("velocity_ms")
    if alt and alt > 10000 and vel and vel < 180:
        # 고고도 저속 = ISR 패턴 (민항기는 보통 200+ m/s)
        if country in ("United States", "Russia", "China", "United Kingdom",
                       "France", "Germany", "Turkey", "Israel", "South Korea",
                       "Japan", "Australia", "Italy"):
            return True

    # 6. 카테고리 (Heavy/High Performance/Rotorcraft in unusual area)
    cat = ac.get("category")
    if cat and cat >= 4:  # Large 이상 (기존 5에서 4로 완화)
        return True

    # 7. 콜사인 없음 + 고고도 = 정체 불명 항공기 (관심 대상)
    if not callsign and alt and alt > 8000:
        return True

    return False


def assess_aircraft(ac):
    """개별 항공기 평가"""
    cs = (ac.get("callsign") or "").upper()
    if any(p in cs for p in ("DUKE", "ETHYL", "IRON")):
        return "공중급유기 → 전투기 작전 가능"
    if "FORTE" in cs:
        return "RQ-4 Global Hawk 고고도 정찰"
    if "JAKE" in cs:
        return "P-8A 해상초계기"
    if any(p in cs for p in ("RCH", "REACH")):
        return "전략수송기 → 병력/장비 전개"
    if any(p in cs for p in ("DOOM", "BONE")):
        return "전략폭격기 활동"
    if ac.get("squawk") == "7700":
        return "비상 선언"
    if ac.get("squawk") == "7500":
        return "하이재킹 코드"
    return "군용기 분류"


def collect_aviation():
    """전체 항공 데이터 수집 실행"""
    print("\n[Aviation] ══ 군용기 데이터 수집 시작 ══")
    print(f"[Aviation] 감시 지역: {len(WATCH_REGIONS)}개")

    results = []
    for key, region in WATCH_REGIONS.items():
        print(f"[Aviation] 수집: {region['name']} ({key})")
        data = fetch_region(key, region)
        results.append(data)
        # Rate limit: 인증 시 5초, 비인증 시 10초
        delay = 6 if (OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET) else 11
        time.sleep(delay)

    # 분석
    summary = {
        "collection_time": datetime.utcnow().isoformat() + "Z",
        "source": "OpenSky Network",
        "classification": "UNCLASSIFIED // OSINT",
        "regions": [],
        "alerts": [],
        "total_military_detected": 0,
    }

    for rd in results:
        if not rd:
            continue

        mil_aircraft = [ac for ac in rd["aircraft"] if is_military(ac)]
        print(f"  → {rd['regionName']}: 전체 {rd['total_aircraft']}대, 군용기 {len(mil_aircraft)}대")

        region_summary = {
            "region": rd["region"],
            "regionName": rd["regionName"],
            "theater": rd["theater"],
            "total_aircraft": rd["total_aircraft"],
            "military_detected": len(mil_aircraft),
            "military_aircraft": [{
                "icao24": ac["icao24"],
                "callsign": ac["callsign"],
                "origin_country": ac["origin_country"],
                "lat": ac["latitude"],
                "lon": ac["longitude"],
                "altitude_ft": round(ac["altitude_m"] * 3.281) if ac["altitude_m"] else None,
                "speed_kts": round(ac["velocity_ms"] * 1.944) if ac["velocity_ms"] else None,
                "heading": ac["heading"],
                "squawk": ac["squawk"],
                "assessment": assess_aircraft(ac),
            } for ac in mil_aircraft]
        }

        summary["regions"].append(region_summary)
        summary["total_military_detected"] += len(mil_aircraft)

        if len(mil_aircraft) >= 10:
            summary["alerts"].append({
                "type": "AIRCRAFT_SURGE",
                "priority": "ELEVATED",
                "region": rd["regionName"],
                "detail": f"{rd['regionName']}에서 군용기 {len(mil_aircraft)}대 동시 탐지",
            })

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"aviation_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Aviation] ══ 완료: 군용기 {summary['total_military_detected']}대, 알림 {len(summary['alerts'])}건 ══")
    print(f"[Aviation] 저장: {out_path}")
    return summary


if __name__ == "__main__":
    collect_aviation()
```

---

## 파일 3: `collectors/maritime.py`

```python
"""
KSPD OSINT Engine — 군함 AIS 수집기 (AISStream.io)
WebSocket으로 감시 지역별 AIS 스냅샷 수집 → 군함 식별

※ 실행 전: pip install websocket-client
"""

import json
import time
import os
import threading
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import AISSTREAM_API_KEY, WATCH_REGIONS, KNOWN_NAVAL_MMSI

SNAPSHOT_SECONDS = 30  # 지역당 30초 수집


def collect_region_snapshot(region_key, region):
    """한 지역의 AIS 데이터를 WebSocket으로 스냅샷 수집"""
    try:
        import websocket
    except ImportError:
        print("  [!] websocket-client 미설치. pip install websocket-client 실행 필요")
        return None

    if not AISSTREAM_API_KEY:
        print(f"  [Skip] {region_key} — AISSTREAM_API_KEY 미설정")
        return None

    vessels = {}
    msg_count = [0]
    done = threading.Event()

    def on_open(ws):
        sub = {
            "APIKey": AISSTREAM_API_KEY,
            "BoundingBoxes": [region["bbox"]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
        }
        ws.send(json.dumps(sub))
        print(f"  연결 완료, {SNAPSHOT_SECONDS}초 수집중...")

    def on_message(ws, data):
        try:
            msg = json.loads(data)
            msg_count[0] += 1
            meta = msg.get("MetaData", {})
            mmsi = str(meta.get("MMSI", ""))
            msg_type = msg.get("MessageType", "")

            if msg_type == "PositionReport":
                pos = msg.get("Message", {}).get("PositionReport", {})
                existing = vessels.get(mmsi, {})
                vessels[mmsi] = {
                    **existing,
                    "mmsi": mmsi,
                    "lat": pos.get("Latitude"),
                    "lon": pos.get("Longitude"),
                    "speed_kts": pos.get("Sog"),
                    "course": pos.get("Cog"),
                    "heading": pos.get("TrueHeading"),
                    "nav_status": pos.get("NavigationalStatus"),
                    "ship_name": meta.get("ShipName") or existing.get("ship_name", ""),
                    "last_seen": meta.get("time_utc", ""),
                }

            elif msg_type == "ShipStaticData":
                sd = msg.get("Message", {}).get("ShipStaticData", {})
                existing = vessels.get(mmsi, {})
                dim = sd.get("Dimension", {})
                vessels[mmsi] = {
                    **existing,
                    "mmsi": mmsi,
                    "ship_name": sd.get("Name") or meta.get("ShipName") or existing.get("ship_name", ""),
                    "ship_type": sd.get("Type"),
                    "callsign": sd.get("CallSign"),
                    "destination": sd.get("Destination"),
                    "length": (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0),
                    "width": (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0),
                    "last_seen": meta.get("time_utc", ""),
                }
        except Exception:
            pass

    def on_error(ws, error):
        print(f"  [WS Error] {error}")

    def on_close(ws, code, msg):
        done.set()

    ws = websocket.WebSocketApp(
        "wss://stream.aisstream.io/v0/stream",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # 별도 스레드에서 WebSocket 실행
    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()

    # 지정 시간 후 종료
    done.wait(timeout=SNAPSHOT_SECONDS + 5)
    ws.close()
    time.sleep(1)

    print(f"  {region_key}: {len(vessels)}척 수집, {msg_count[0]}건 메시지")

    return {
        "region": region_key,
        "regionName": region["name"],
        "theater": region["theater"],
        "priority": region["priority"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "total_vessels": len(vessels),
        "messages": msg_count[0],
        "vessels": list(vessels.values())
    }


def classify_vessel(v):
    """군함 식별 (완화된 필터)"""
    mmsi = v.get("mmsi", "")

    # 알려진 군함
    if mmsi in KNOWN_NAVAL_MMSI:
        info = KNOWN_NAVAL_MMSI[mmsi]
        return {**v, **info, "classification": "CONFIRMED_NAVAL", "confidence": "A-1"}

    # 선박 유형 체크 (AIS ship type codes)
    ship_type = v.get("ship_type")
    if ship_type in (35, 55):  # 35=Military, 55=Law Enforcement
        return {**v, "classification": "PROBABLE_NAVAL", "confidence": "B-2",
                "assessment": f"AIS 선박유형 {ship_type} 기반 군함/법집행 추정"}

    # 정부 선박 유형
    if ship_type in (51, 52, 53, 54, 55):  # 5x = Special craft
        return {**v, "classification": "POSSIBLE_GOVT", "confidence": "C-3",
                "assessment": f"정부/특수 선박 (type {ship_type})"}

    # 대형 고속 선박
    length = v.get("length", 0) or 0
    speed = v.get("speed_kts", 0) or 0
    if length > 80 and speed > 18:
        return {**v, "classification": "POSSIBLE_NAVAL", "confidence": "C-4",
                "assessment": f"대형 고속 ({length}m, {speed}kts) — 군함/고속정 가능성"}

    # 콜사인/이름에 군사 관련 키워드
    name = (v.get("ship_name") or "").upper()
    callsign = (v.get("callsign") or "").upper()
    NAV_KEYWORDS = ("NAVY", "COAST GUARD", "WARSHIP", "FRIGATE", "CORVETTE",
                    "DESTROYER", "PATROL", "USCG", "HMS", "USS")
    if any(kw in name for kw in NAV_KEYWORDS) or any(kw in callsign for kw in NAV_KEYWORDS):
        return {**v, "classification": "PROBABLE_NAVAL", "confidence": "B-3",
                "assessment": f"이름/콜사인에서 군함 키워드 탐지: {name or callsign}"}

    # 목적지가 군항인 경우
    dest = (v.get("destination") or "").upper()
    MIL_PORTS = ("NORFOLK", "SAN DIEGO", "PEARL HARBOR", "YOKOSUKA", "SASEBO",
                 "BAHRAIN", "DJIBOUTI", "ROTA", "SOUDA BAY", "DIEGO GARCIA",
                 "SUBIC", "CHANGI", "BUSAN NAVAL", "JINHAE", "PYEONGTAEK")
    if any(p in dest for p in MIL_PORTS):
        return {**v, "classification": "INTEREST_NAVAL_PORT", "confidence": "D-4",
                "assessment": f"목적지 군항: {dest}"}

    return {**v, "classification": "CIVILIAN"}


def collect_maritime():
    """해상 AIS 전체 수집"""
    print("\n[Maritime] ══ 해상 AIS 수집 시작 ══")

    if not AISSTREAM_API_KEY:
        print("[Maritime] ⚠ AISSTREAM_API_KEY 미설정 — 건너뜀")
        return {"collection_time": datetime.utcnow().isoformat() + "Z",
                "source": "AISStream.io (SKIPPED)", "regions": [], "alerts": [],
                "total_naval_detected": 0, "dark_ships": []}

    # HIGH 우선순위 지역부터
    sorted_regions = sorted(WATCH_REGIONS.items(),
                            key=lambda x: {"CRITICAL": 0, "HIGH": 1, "ELEVATED": 2, "MEDIUM": 3}.get(x[1]["priority"], 4))

    results = []
    for key, region in sorted_regions:
        print(f"[Maritime] 수집: {region['name']} ({key}) [{region['priority']}]")
        data = collect_region_snapshot(key, region)
        results.append(data)
        time.sleep(3)

    # 분석
    summary = {
        "collection_time": datetime.utcnow().isoformat() + "Z",
        "source": "AISStream.io",
        "classification": "UNCLASSIFIED // OSINT",
        "regions": [],
        "alerts": [],
        "total_vessels_scanned": 0,
        "total_naval_detected": 0,
        "dark_ships": [],
    }

    for rd in results:
        if not rd:
            continue
        classified = [classify_vessel(v) for v in rd["vessels"]]
        naval = [v for v in classified if v["classification"] != "CIVILIAN"]
        interest = [v for v in classified if v["classification"] in ("INTEREST_NAVAL_PORT",)]

        print(f"  → {rd['regionName']}: 전체 {rd['total_vessels']}척, 관심 {len(naval)}척")

        summary["regions"].append({
            "region": rd["region"],
            "regionName": rd["regionName"],
            "theater": rd["theater"],
            "total_vessels": rd["total_vessels"],
            "naval_detected": len(naval),
            "naval_vessels": [{
                "mmsi": v["mmsi"], "name": v.get("ship_name") or v.get("name", "UNKNOWN"),
                "type": v.get("type", f"type_{v.get('ship_type','')}"),
                "nation": v.get("nation", ""),
                "lat": v.get("lat"), "lon": v.get("lon"),
                "speed_kts": v.get("speed_kts"), "course": v.get("course"),
                "classification": v["classification"], "confidence": v.get("confidence"),
                "assessment": v.get("assessment", ""),
            } for v in naval]
        })
        summary["total_vessels_scanned"] += rd["total_vessels"]
        summary["total_naval_detected"] += len(naval)

        for v in naval:
            if v["classification"] == "CONFIRMED_NAVAL":
                summary["alerts"].append({
                    "type": "CONFIRMED_NAVAL",
                    "priority": "HIGH" if v.get("type") == "carrier" else "ELEVATED",
                    "detail": f"{v.get('name',v.get('ship_name','?'))} ({v.get('nation','?')}) — {rd['regionName']} AIS 포착",
                })

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"maritime_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Maritime] ══ 완료: 스캔 {summary['total_vessels_scanned']}척, 군함 {summary['total_naval_detected']}척 ══")
    return summary


if __name__ == "__main__":
    collect_maritime()
```

---

## 파일 4: `collectors/conflicts.py`

```python
"""
KSPD OSINT Engine — 분쟁 이벤트 수집기
1. GDELT Project (무료, 키 불필요) — 군사/분쟁 뉴스
2. ACLED (OAuth 인증) — 분쟁 이벤트 데이터
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import ACLED_EMAIL, ACLED_PASSWORD, WATCH_COUNTRIES


def fetch_gdelt():
    """GDELT API — 군사/분쟁 관련 최신 뉴스 수집 (무료, 키 불필요)"""
    print("[Conflicts] GDELT 뉴스 수집...")
    # 쿼리를 짧고 단순하게 (타임아웃 방지)
    queries = [
        "military Middle East",
        "carrier deployment",
        "Taiwan military",
        "Ukraine frontline",
        "North Korea",
        "NATO exercise",
        "Houthi attack",
        "Iran strike",
    ]

    all_articles = []
    fail_count = 0
    session = requests.Session()  # 연결 재사용으로 타임아웃 완화
    for q in queries:
        if fail_count >= 3:
            print(f"  GDELT 연속 실패 — 나머지 쿼리 건너뜀")
            break
        try:
            url = (f"https://api.gdeltproject.org/api/v2/doc/doc?"
                   f"query={requests.utils.quote(q)}&mode=artlist"
                   f"&maxrecords=10&format=json&timespan=24h")
            resp = session.get(url, timeout=20)
            if resp.ok:
                data = resp.json()
                for a in data.get("articles", []):
                    all_articles.append({
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("domain", ""),
                        "date": a.get("seendate", ""),
                        "language": a.get("language", ""),
                        "query": q,
                    })
                fail_count = 0  # 성공하면 리셋
                print(f"  GDELT '{q}': {len(data.get('articles', []))}건")
            else:
                print(f"  GDELT '{q}': HTTP {resp.status_code}")
                fail_count += 1
        except requests.exceptions.Timeout:
            print(f"  GDELT '{q}' 타임아웃 — 건너뜀")
            fail_count += 1
        except Exception as e:
            print(f"  GDELT '{q}' 실패: {e}")
            fail_count += 1
        time.sleep(2)

    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    print(f"  GDELT: {len(unique)}건 수집")
    return unique


def get_acled_token():
    """ACLED OAuth 토큰 발급"""
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        return None

    try:
        resp = requests.post(
            "https://acleddata.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "username": ACLED_EMAIL,
                "password": ACLED_PASSWORD,
                "grant_type": "password",
                "client_id": "acled",
            },
            timeout=15,
        )
        if resp.ok:
            return resp.json().get("access_token")
        else:
            print(f"  ACLED 토큰 실패: {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ACLED 토큰 오류: {e}")
        return None


def fetch_acled(token, countries, theater):
    """ACLED API에서 최근 7일 분쟁 데이터 수집"""
    if not token:
        return None

    seven_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    country_filter = "|".join(countries)

    url = (f"https://acleddata.com/api/acled/read?_format=json"
           f"&country={requests.utils.quote(country_filter)}"
           f"&event_date={seven_ago}|{today}&event_date_where=BETWEEN"
           f"&limit=300"
           f"&fields=event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2"
           f"|country|admin1|location|latitude|longitude|fatalities|notes")

    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if resp.ok:
            data = resp.json()
            events = data.get("data", [])
            print(f"  ACLED {theater}: {len(events)}건")
            return {"theater": theater, "events": events}
        else:
            print(f"  ACLED {theater}: HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ACLED {theater} 오류: {e}")
        return None


EVENT_TYPE_KR = {
    "Battles": "전투",
    "Violence against civilians": "민간인 대상 폭력",
    "Explosions/Remote violence": "폭발/원격 폭력",
    "Riots": "폭동",
    "Protests": "시위",
    "Strategic developments": "전략적 전개",
}


def collect_conflicts():
    """전체 분쟁 데이터 수집"""
    print("\n[Conflicts] ══ 분쟁 이벤트 수집 시작 ══")

    # GDELT (항상 가능)
    gdelt_articles = fetch_gdelt()

    # ACLED (유료 라이선스 필요 — Open 레벨에서는 API 접근 불가)
    acled_results = []
    token = get_acled_token()
    if token:
        print("[Conflicts] ACLED 토큰 발급 성공, API 접근 시도...")
        # 첫 theater로 접근 테스트
        first_theater = list(WATCH_COUNTRIES.items())[0]
        test_result = fetch_acled(token, first_theater[1], first_theater[0])
        if test_result:
            acled_results.append(test_result)
            for theater, countries in list(WATCH_COUNTRIES.items())[1:]:
                print(f"[Conflicts] ACLED 수집: {theater}")
                result = fetch_acled(token, countries, theater)
                acled_results.append(result)
                time.sleep(2)
        else:
            print("[Conflicts] ⚠ ACLED API 접근 거부 — Open 레벨은 유료 라이선스 필요 (GDELT만 사용)")
    else:
        print("[Conflicts] ⚠ ACLED 토큰 발급 실패 — GDELT만 사용")

    # 분석
    summary = {
        "collection_time": datetime.utcnow().isoformat() + "Z",
        "sources": ["GDELT"] + (["ACLED"] if token else []),
        "classification": "UNCLASSIFIED // OSINT",
        "theaters": [],
        "event_statistics": {"total_events": 0, "total_fatalities": 0},
        "gdelt_headlines": gdelt_articles[:30],
        "alerts": [],
    }

    for r in acled_results:
        if not r:
            continue
        events = r["events"]
        by_type = {}
        by_country = {}
        total_fat = 0

        for e in events:
            t = e.get("event_type", "")
            by_type[t] = by_type.get(t, 0) + 1
            c = e.get("country", "")
            by_country[c] = by_country.get(c, 0) + 1
            total_fat += int(e.get("fatalities", 0) or 0)

        theater_summary = {
            "theater": r["theater"],
            "total_events": len(events),
            "total_fatalities": total_fat,
            "by_type": [{"type": k, "type_kr": EVENT_TYPE_KR.get(k, k), "count": v}
                        for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            "by_country": [{"country": k, "count": v}
                           for k, v in sorted(by_country.items(), key=lambda x: -x[1])[:5]],
            "deadliest": sorted(
                [e for e in events if int(e.get("fatalities", 0) or 0) > 0],
                key=lambda e: -int(e.get("fatalities", 0) or 0)
            )[:5],
        }
        summary["theaters"].append(theater_summary)
        summary["event_statistics"]["total_events"] += len(events)
        summary["event_statistics"]["total_fatalities"] += total_fat

        if len(events) > 50:
            summary["alerts"].append({
                "type": "CONFLICT_SPIKE",
                "priority": "HIGH" if total_fat > 100 else "ELEVATED",
                "detail": f"{r['theater']}: 7일간 {len(events)}건, 사상자 {total_fat}명",
            })

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"conflicts_{datetime.utcnow().strftime('%Y%m%d')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Conflicts] ══ 완료: ACLED {summary['event_statistics']['total_events']}건, GDELT {len(gdelt_articles)}건 ══")
    return summary


if __name__ == "__main__":
    collect_conflicts()
```

---

## 파일 5: `collectors/thermal.py` (변경 없음)

```python
"""
KSPD OSINT Engine — NASA FIRMS 열 이상 수집기
군사시설 인근 위성 열점 탐지 (폭격, 화재, 시설 활동)
"""

import requests
import json
import math
import time
import os
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import FIRMS_MAP_KEY, MILITARY_FACILITIES

THERMAL_REGIONS = [
    {"name": "이란", "bbox": "44,25,64,40", "theater": "middleEast"},
    {"name": "이스라엘/레바논/시리아", "bbox": "34,29,37,34", "theater": "middleEast"},
    {"name": "예멘", "bbox": "42,12,54,19", "theater": "middleEast"},
    {"name": "우크라이나", "bbox": "22,44,40,53", "theater": "europe"},
    {"name": "한반도", "bbox": "124,33,132,43", "theater": "indoPacific"},
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_firms_region(region):
    """NASA FIRMS CSV API로 열점 데이터 수집"""
    map_key = FIRMS_MAP_KEY or "OPEN"
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/VIIRS_SNPP_NRT/{region['bbox']}/2"

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  FIRMS {region['name']}: HTTP {resp.status_code}")
            return None

        lines = resp.text.strip().split("\n")
        if len(lines) < 2:
            return {"name": region["name"], "theater": region["theater"], "hotspots": []}

        headers = [h.strip() for h in lines[0].split(",")]
        hotspots = []
        for line in lines[1:]:
            vals = line.split(",")
            row = dict(zip(headers, [v.strip() for v in vals]))
            try:
                hotspots.append({
                    "lat": float(row.get("latitude", 0)),
                    "lon": float(row.get("longitude", 0)),
                    "brightness": float(row.get("bright_ti4", row.get("brightness", 0))),
                    "confidence": row.get("confidence", ""),
                    "frp": float(row.get("frp", 0)),
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "daynight": row.get("daynight", ""),
                })
            except (ValueError, KeyError):
                continue

        return {"name": region["name"], "theater": region["theater"], "hotspots": hotspots}

    except Exception as e:
        print(f"  FIRMS {region['name']} 오류: {e}")
        return None


def check_military_proximity(all_hotspots):
    """군사 시설 인근 열 이상 탐지"""
    alerts = []
    for fac in MILITARY_FACILITIES:
        nearby = [h for h in all_hotspots
                  if haversine_km(fac["lat"], fac["lon"], h["lat"], h["lon"]) <= fac["radius_km"]]
        if nearby:
            high_conf = [h for h in nearby if h["confidence"] in ("high", "h") or
                         (h["confidence"].isdigit() and int(h["confidence"]) >= 80)]
            alerts.append({
                "facility": fac["name"],
                "lat": fac["lat"], "lon": fac["lon"],
                "total_nearby": len(nearby),
                "high_confidence": len(high_conf),
                "max_frp": max(h["frp"] for h in nearby),
                "closest_km": round(min(haversine_km(fac["lat"], fac["lon"], h["lat"], h["lon"])
                                        for h in nearby), 1),
            })
    return alerts


def collect_thermal():
    """전체 열 이상 수집"""
    print("\n[Thermal] ══ NASA FIRMS 열 이상 수집 시작 ══")

    results = []
    all_hotspots = []
    for region in THERMAL_REGIONS:
        print(f"[Thermal] 수집: {region['name']}")
        data = fetch_firms_region(region)
        results.append(data)
        if data:
            all_hotspots.extend(data["hotspots"])
        time.sleep(3)

    mil_alerts = check_military_proximity(all_hotspots)

    summary = {
        "collection_time": datetime.utcnow().isoformat() + "Z",
        "source": "NASA FIRMS (VIIRS SNPP)",
        "classification": "UNCLASSIFIED // OSINT",
        "period": "최근 48시간",
        "regions": [{
            "region": r["name"], "theater": r["theater"],
            "total_hotspots": len(r["hotspots"]),
        } for r in results if r],
        "military_proximity_alerts": mil_alerts,
        "alerts": [],
        "statistics": {"total_hotspots": len(all_hotspots)},
    }

    for ma in mil_alerts:
        if ma["high_confidence"] > 0:
            summary["alerts"].append({
                "type": "THERMAL_MILITARY",
                "priority": "HIGH" if ma["high_confidence"] >= 3 else "ELEVATED",
                "detail": f"{ma['facility']} 반경 {ma['closest_km']}km 내 열점 {ma['total_nearby']}건 (고신뢰 {ma['high_confidence']}건)",
            })

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"thermal_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Thermal] ══ 완료: 열점 {len(all_hotspots)}건, 군사시설 알림 {len(mil_alerts)}건 ══")
    return summary


if __name__ == "__main__":
    collect_thermal()
```

---

## 파일 6: `main.py`

```python
"""
KSPD OSINT Engine — 메인 실행 파이프라인
전체 수집 → 종합 분석 → AI 브리핑 생성

사용법:
    python main.py              # 전체 실행
    python main.py --aviation   # 항공만
    python main.py --maritime   # 해상만
    python main.py --conflicts  # 분쟁만
    python main.py --thermal    # 열이상만
"""

import json
import os
import sys
import time
import requests
from datetime import datetime

from collectors.aviation import collect_aviation
from collectors.maritime import collect_maritime
from collectors.conflicts import collect_conflicts
from collectors.thermal import collect_thermal
from config.settings import GEMINI_API_KEY

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def generate_briefing(data):
    """Gemini API로 ICD 203 형식 한국어 브리핑 생성"""
    if not GEMINI_API_KEY:
        print("[Briefing] GEMINI_API_KEY 미설정 — 자동 요약으로 대체")
        return auto_briefing(data)

    # 수집 데이터 요약 (프롬프트 토큰 절약)
    data_summary = {
        "aviation": {
            "total_military": data.get("aviation", {}).get("total_military_detected", 0),
            "total_scanned": sum(r.get("total_aircraft", 0) for r in data.get("aviation", {}).get("regions", [])),
            "regions": [{
                "name": r["regionName"], "total": r.get("total_aircraft", 0), "mil": r["military_detected"],
                "notable": [{"cs": a["callsign"], "country": a["origin_country"], "assess": a["assessment"]}
                            for a in r.get("military_aircraft", [])[:3]]
            } for r in data.get("aviation", {}).get("regions", []) if r.get("military_detected", 0) > 0]
        },
        "maritime": {
            "total_scanned": data.get("maritime", {}).get("total_vessels_scanned", 0),
            "total_naval": data.get("maritime", {}).get("total_naval_detected", 0),
            "vessels": [{
                "name": v["name"], "nation": v.get("nation", ""), "region": r["regionName"],
                "classification": v["classification"]
            } for r in data.get("maritime", {}).get("regions", [])
              for v in r.get("naval_vessels", [])[:3]]
        },
        "conflicts": {
            "total_events": data.get("conflicts", {}).get("event_statistics", {}).get("total_events", 0),
            "fatalities": data.get("conflicts", {}).get("event_statistics", {}).get("total_fatalities", 0),
            "theaters": [{
                "name": t["theater"], "events": t["total_events"], "fatalities": t["total_fatalities"]
            } for t in data.get("conflicts", {}).get("theaters", [])]
        },
        "thermal": {
            "total_hotspots": data.get("thermal", {}).get("statistics", {}).get("total_hotspots", 0),
            "regions": [{
                "name": r["region"], "hotspots": r["total_hotspots"]
            } for r in data.get("thermal", {}).get("regions", []) if r.get("total_hotspots", 0) > 0],
            "military_alerts": [{
                "facility": a["facility"], "nearby": a["total_nearby"],
                "high_confidence": a.get("high_confidence", 0), "closest_km": a.get("closest_km")
            } for a in data.get("thermal", {}).get("military_proximity_alerts", [])],
        },
        "headlines": [a["title"] for a in data.get("conflicts", {}).get("gdelt_headlines", [])[:10]],
    }

    today_mmdd = datetime.utcnow().strftime("%m%d")
    prompt = f"""당신은 KSPD THE ONE 유현인텔리전스의 수석 OSINT 분석관입니다.
아래 수집 데이터를 기반으로 **한국어** 일일 정보 브리핑을 작성하세요.

형식: ICD 203 정보 분석 표준 준용
분류: UNCLASSIFIED // OSINT

=== 수집 데이터 ===
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

=== 작성 지침 ===
1. 제목: "일일 정보 브리핑 #{today_mmdd}"
2. 핵심 판단 3~5개, 각 항목에 ICD 203 확률 용어 사용
   (Almost Certain/Very Likely/Likely/Roughly Even Chance/Unlikely/Very Unlikely/Remote)
3. 전구별 상황: 중동, 인도태평양, 유럽 (각 2~3문단)
4. 정보 공백 (Intelligence Gaps)
5. 전망 (향후 24~72시간)

톤: 간결, 객관적. 사실과 평가를 구분. 2,000~3,000자.
한국어로 작성하세요."""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096}
            },
            timeout=120,
        )
        if resp.ok:
            text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if text:
                return {"generated_by": "Gemini + KSPD OSINT Desk", "briefing_text": text,
                        "generated_at": datetime.utcnow().isoformat() + "Z", "icd203": True}
        print(f"[Briefing] Gemini 응답 오류: {resp.status_code}")
    except Exception as e:
        print(f"[Briefing] Gemini 오류: {e}")

    return auto_briefing(data)


def auto_briefing(data):
    """AI 없을 때 데이터 기반 자동 브리핑"""
    now = datetime.utcnow()
    lines = []
    lines.append(f"# 일일 정보 브리핑 #{now.strftime('%m%d')}")
    lines.append(f"\n**분류:** UNCLASSIFIED // OSINT")
    lines.append(f"**작성:** {now.strftime('%Y-%m-%d %H:%M')} UTC | KSPD OSINT Desk")
    lines.append(f"**출처:** OpenSky, AISStream, GDELT, NASA FIRMS\n")
    lines.append("## 핵심 판단\n")

    av = data.get("aviation", {})
    lines.append(f"- 군용기 {av.get('total_military_detected', 0)}대 탐지")

    mt = data.get("maritime", {})
    lines.append(f"- 군함 {mt.get('total_naval_detected', 0)}척 AIS 포착, AIS 소실 {len(mt.get('dark_ships', []))}척")

    cf = data.get("conflicts", {}).get("event_statistics", {})
    lines.append(f"- 분쟁: 7일간 {cf.get('total_events', 0)}건, 사상자 {cf.get('total_fatalities', 0)}명")

    th = data.get("thermal", {})
    th_total = th.get("statistics", {}).get("total_hotspots", 0)
    th_mil = len(th.get("military_proximity_alerts", []))
    lines.append(f"- 위성 열점: {th_total}건 탐지, 군사시설 인근 {th_mil}건\n")

    # 알림 취합
    all_alerts = []
    for key in ("aviation", "maritime", "conflicts", "thermal"):
        all_alerts.extend(data.get(key, {}).get("alerts", []))

    if all_alerts:
        lines.append("## 주요 알림\n")
        for a in all_alerts[:10]:
            lines.append(f"**[{a.get('priority','')}]** {a.get('detail','')}\n")

    # GDELT 헤드라인
    headlines = data.get("conflicts", {}).get("gdelt_headlines", [])[:5]
    if headlines:
        lines.append("\n## 주요 뉴스 (GDELT)\n")
        for h in headlines:
            lines.append(f"- {h.get('title','')} ({h.get('source','')})")

    lines.append(f"\n---\n*공개 출처 정보(OSINT) 기반 자동 생성. 기밀 정보 미포함.*")

    text = "\n".join(lines)
    return {"generated_by": "KSPD OSINT Desk (Auto)", "briefing_text": text,
            "generated_at": datetime.utcnow().isoformat() + "Z", "icd203": False}


def main():
    start = time.time()
    print("╔══════════════════════════════════════════════╗")
    print("║  KSPD THE ONE — OSINT Collection Engine      ║")
    print("║  Global Military Intelligence Pipeline       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"시작: {datetime.utcnow().isoformat()}Z\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    args = sys.argv[1:]
    run_all = not args

    data = {}

    # 수집
    if run_all or "--aviation" in args:
        try:
            data["aviation"] = collect_aviation()
        except Exception as e:
            print(f"[!] Aviation 실패: {e}")

    if run_all or "--conflicts" in args:
        try:
            data["conflicts"] = collect_conflicts()
        except Exception as e:
            print(f"[!] Conflicts 실패: {e}")

    if run_all or "--thermal" in args:
        try:
            data["thermal"] = collect_thermal()
        except Exception as e:
            print(f"[!] Thermal 실패: {e}")

    if run_all or "--maritime" in args:
        try:
            data["maritime"] = collect_maritime()
        except Exception as e:
            print(f"[!] Maritime 실패: {e}")

    # AI 브리핑
    print("\n━━━ AI 브리핑 생성 ━━━")
    briefing = generate_briefing(data)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    # 브리핑 텍스트 저장
    md_path = os.path.join(OUTPUT_DIR, f"briefing_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(briefing["briefing_text"])

    # 브리핑 메타 저장
    json_path = os.path.join(OUTPUT_DIR, f"briefing_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)

    # 상태 파일
    elapsed = round(time.time() - start)
    status = {
        "last_run": datetime.utcnow().isoformat() + "Z",
        "duration_sec": elapsed,
        "aviation_mil": data.get("aviation", {}).get("total_military_detected", 0),
        "maritime_naval": data.get("maritime", {}).get("total_naval_detected", 0),
        "conflicts_events": data.get("conflicts", {}).get("event_statistics", {}).get("total_events", 0),
        "thermal_hotspots": data.get("thermal", {}).get("statistics", {}).get("total_hotspots", 0),
        "alerts": sum(len(data.get(k, {}).get("alerts", [])) for k in ("aviation", "maritime", "conflicts", "thermal")),
        "briefing": md_path,
    }
    with open(os.path.join(OUTPUT_DIR, "latest_status.json"), "w") as f:
        json.dump(status, f, indent=2)

    print(f"\n╔══════════════════════════════════════════════╗")
    print(f"║  완료 ({elapsed}초)                            ║")
    print(f"╚══════════════════════════════════════════════╝")
    print(f"군용기: {status['aviation_mil']}대 | 군함: {status['maritime_naval']}척")
    print(f"분쟁: {status['conflicts_events']}건 | 열점: {status['thermal_hotspots']}건")
    print(f"알림: {status['alerts']}건")
    print(f"브리핑: {md_path}")


if __name__ == "__main__":
    main()
```

---

## 적용 후 확인

```bash
cd C:\work\kspd-osint-py\kspd-osint-py
python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['config/settings.py','collectors/aviation.py','collectors/maritime.py','collectors/conflicts.py','collectors/thermal.py','main.py']]; print('All OK')"
python main.py
```
