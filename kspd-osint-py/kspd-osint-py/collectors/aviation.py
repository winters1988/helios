"""
KSPD OSINT Engine - 군용기 수집기 (OpenSky Network)
OpenSky REST API로 감시 지역별 항공기 데이터 수집 -> 군용기 필터링
"""

import requests
import json
import time
import os
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET,
    WATCH_REGIONS, MILITARY_CALLSIGN_PATTERNS
)

OPENSKY_BASE = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

_opensky_token_cache = {"token": None, "expires": 0}


def get_opensky_token():
    """OpenSky OAuth2 client_credentials 토큰 발급"""
    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return None

    now = time.time()
    if _opensky_token_cache["token"] and now < _opensky_token_cache["expires"]:
        return _opensky_token_cache["token"]

    try:
        resp = requests.post(OPENSKY_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": OPENSKY_CLIENT_ID,
            "client_secret": OPENSKY_CLIENT_SECRET,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)

        if resp.ok:
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 1800)
            _opensky_token_cache["token"] = token
            _opensky_token_cache["expires"] = now + expires_in - 60
            print("[Aviation] OpenSky OAuth2 토큰 발급 성공")
            return token
        else:
            print(f"[Aviation] OpenSky 토큰 실패: HTTP {resp.status_code} - {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"[Aviation] OpenSky 토큰 오류: {e}")
        return None


def fetch_region(region_key, region, token=None):
    """OpenSky API로 특정 지역 항공기 데이터 수집"""
    (lat_min, lon_min), (lat_max, lon_max) = region["bbox"]
    url = f"{OPENSKY_BASE}/states/all"
    params = {
        "lamin": lat_min, "lomin": lon_min,
        "lamax": lat_max, "lomax": lon_max
    }

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 429:
            print(f"  [Rate Limit] {region_key} - 10초 대기 후 재시도")
            time.sleep(12)
            resp = requests.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code != 200:
            print(f"  [Error] {region_key}: HTTP {resp.status_code}")
            return None

        data = resp.json()
        states = data.get("states") or []

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


CIVIL_CALLSIGN_PREFIXES = (
    "CPA", "CCA", "CSN", "CES",  # 캐세이퍼시픽, 에어차이나, 중국남방, 중국동방
    "AAR", "KAL", "JNA", "TWB",  # 아시아나, 대한항공, 진에어, 티웨이
    "ANA", "JAL", "JJP", "APJ",  # ANA, JAL, 제트스타재팬, 피치
    "UAE", "QTR", "ETH", "SIA",  # 에미레이트, 카타르, 에티오피아, 싱가포르
    "BAW", "DLH", "AFR", "KLM",  # 영국항공, 루프트한자, 에어프랑스, KLM
    "AAL", "DAL", "UAL", "SWA",  # 아메리칸, 델타, 유나이티드, 사우스웨스트
    "THY", "SVA", "GIA", "MAS",  # 터키항공, 사우디아, 가루다, 말레이시아
    "FDX", "UPS",                # FedEx, UPS (화물)
)


def is_military(ac):
    """군용기 판별"""
    callsign = (ac.get("callsign") or "").upper()

    # 0. 민항사 콜사인 제외
    if callsign and any(callsign.startswith(p) for p in CIVIL_CALLSIGN_PREFIXES):
        return False

    # 1. 콜사인 패턴 매칭
    for pattern in MILITARY_CALLSIGN_PATTERNS:
        if pattern.search(callsign):
            return True

    # 2. 비상 스쿼크
    if ac.get("squawk") in ("7500", "7600", "7700"):
        return True

    # 3. 고고도 + 저속 (ISR 패턴) - 콜사인 없는 경우만
    alt = ac.get("altitude_m")
    vel = ac.get("velocity_ms")
    if alt and alt > 12000 and vel and vel < 200:
        country = ac.get("origin_country", "")
        if country in ("United States", "Russia", "China", "United Kingdom"):
            if not callsign:
                return True

    # 4. 카테고리 (High Performance만, cat >= 5 중 Heavy는 민항기도 포함)
    # OpenSky 카테고리: 5=Heavy(>300k lbs), 6=High Performance(>5g, >400kts)
    # Heavy는 민항기(B747 등) 포함이므로 6 이상만 군용기로 판별
    cat = ac.get("category")
    if cat and cat >= 6:
        return True

    return False


def assess_aircraft(ac):
    """개별 항공기 평가"""
    cs = (ac.get("callsign") or "").upper()
    if any(p in cs for p in ("DUKE", "ETHYL", "IRON")):
        return "공중급유기 -> 전투기 작전 가능"
    if "FORTE" in cs:
        return "RQ-4 Global Hawk 고고도 정찰"
    if "JAKE" in cs:
        return "P-8A 해상초계기"
    if any(p in cs for p in ("RCH", "REACH")):
        return "전략수송기 -> 병력/장비 전개"
    if any(p in cs for p in ("DOOM", "BONE")):
        return "전략폭격기 활동"
    if ac.get("squawk") == "7700":
        return "비상 선언"
    if ac.get("squawk") == "7500":
        return "하이재킹 코드"
    return "군용기 분류"


def collect_aviation():
    """전체 항공 데이터 수집 실행"""
    print("\n[Aviation] == 군용기 데이터 수집 시작 ==")
    print(f"[Aviation] 감시 지역: {len(WATCH_REGIONS)}개")

    token = get_opensky_token()

    results = []
    for key, region in WATCH_REGIONS.items():
        print(f"[Aviation] 수집: {region['name']} ({key})")
        data = fetch_region(key, region, token=token)
        results.append(data)
        # Rate limit: 인증 시 5초, 비인증 시 10초
        delay = 6 if token else 11
        time.sleep(delay)

    # 분석
    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
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
        print(f"  {rd['regionName']}: 항공기 {rd['total_aircraft']}대, 군용기 {len(mil_aircraft)}대")

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
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"aviation_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Aviation] == 완료: 군용기 {summary['total_military_detected']}대, 알림 {len(summary['alerts'])}건 ==")
    print(f"[Aviation] 저장: {out_path}")
    return summary


if __name__ == "__main__":
    collect_aviation()
