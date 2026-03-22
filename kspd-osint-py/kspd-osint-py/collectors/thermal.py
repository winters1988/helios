"""
KSPD OSINT Engine — NASA FIRMS 열 이상 수집기
군사시설 인근 위성 열점 탐지 (폭격, 화재, 시설 활동)
"""

import requests
import json
import math
import time
import os
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import FIRMS_MAP_KEY, MILITARY_FACILITIES

THERMAL_REGIONS = [
    {"name": "이란", "bbox": "44,25,64,40", "theater": "middleEast"},
    {"name": "이스라엘/레바논/시리아", "bbox": "34,29,37,34", "theater": "middleEast"},
    {"name": "예멘", "bbox": "42,12,54,19", "theater": "middleEast"},
    {"name": "우크라이나", "bbox": "22,44,40,53", "theater": "europe"},
    # 한반도: 남북 분리 수집 (DMZ 기준 ~38.0도)
    {"name": "북한", "bbox": "124,37.8,131,43", "theater": "indoPacific"},
    {"name": "남한", "bbox": "125,33,130,37.8", "theater": "indoPacific"},
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_firms_region(region):
    """NASA FIRMS CSV API로 열점 데이터 수집"""
    if not FIRMS_MAP_KEY:
        return None

    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/VIIRS_SNPP_NRT/{region['bbox']}/2"

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  FIRMS {region['name']}: HTTP {resp.status_code}")
            return None

        # API 키 무효 응답 체크
        if "Invalid MAP_KEY" in resp.text:
            print(f"  FIRMS {region['name']}: MAP_KEY 무효 — https://firms.modaps.eosdis.nasa.gov/api/area/ 에서 발급 필요")
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
                         (isinstance(h["confidence"], str) and h["confidence"].isdigit() and int(h["confidence"]) >= 80)]
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
    if not FIRMS_MAP_KEY:
        print("[Thermal] ⚠ FIRMS_MAP_KEY 미설정 — 건너뜀 (https://firms.modaps.eosdis.nasa.gov/api/area/ 에서 발급)")
        return {
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "source": "NASA FIRMS (SKIPPED)", "classification": "UNCLASSIFIED // OSINT",
            "period": "최근 48시간", "regions": [], "military_proximity_alerts": [],
            "alerts": [], "statistics": {"total_hotspots": 0},
        }

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

    # 계절별 농업 소각 맥락 (월 기준)
    month = datetime.now(timezone.utc).month
    seasonal_context = {}
    if month in (2, 3, 4):  # 봄
        seasonal_context = {
            "이란": "2~4월 농업 소각 최성기. 열점 대다수는 농업 활동 추정",
            "북한": "3~4월 산림 소각/농업 준비 시기. 단, 군사시설 인근 열점은 별도 분석 필요",
            "남한": "3~4월 논밭 소각 시기. 열점 대다수는 농업 소각 추정",
            "우크라이나": "3~4월 농업 소각 시기이나, 분쟁 지역 열점은 교전 가능성 병존",
        }
    elif month in (6, 7, 8):  # 여름
        seasonal_context = {
            "이란": "여름 산불 시기. 고온 건조로 자연 발화 가능",
            "북한": "농업 소각 비수기. 열점은 군사 훈련/산업/산불 가능성 주의",
            "남한": "농업 소각 비수기. 열점은 산불 또는 산업 활동 가능",
            "우크라이나": "산불 및 분쟁 관련 열점 혼재",
        }
    elif month in (10, 11):  # 가을
        seasonal_context = {
            "이란": "추수 후 소각 시기. 농업 열점 증가 가능",
            "북한": "추수 후 소각 시기. 열점 증가 일반적이나 군사시설 인근 주의",
            "남한": "10~11월 추수 후 소각. 열점 증가 일반적",
            "우크라이나": "농업 소각 및 분쟁 관련 열점 혼재",
        }

    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "source": "NASA FIRMS (VIIRS SNPP)",
        "classification": "UNCLASSIFIED // OSINT",
        "period": "최근 48시간",
        "seasonal_context": seasonal_context,
        "regions": [{
            "region": r["name"], "theater": r["theater"],
            "total_hotspots": len(r["hotspots"]),
            "seasonal_note": seasonal_context.get(r["name"], ""),
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
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"thermal_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Thermal] ══ 완료: 열점 {len(all_hotspots)}건, 군사시설 알림 {len(mil_alerts)}건 ══")
    return summary


if __name__ == "__main__":
    collect_thermal()
