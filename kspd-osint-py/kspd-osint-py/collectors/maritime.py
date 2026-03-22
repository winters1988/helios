"""
KSPD OSINT Engine - 군함 AIS 수집기 (AISStream.io)
WebSocket으로 감시 지역별 AIS 스냅샷 수집 -> 군함 식별

※ 실행 전: pip install websocket-client
"""

import json
import time
import os
import threading
from datetime import datetime, timezone

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
        print(f"  [Skip] {region_key} - AISSTREAM_API_KEY 미설정")
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_vessels": len(vessels),
        "messages": msg_count[0],
        "vessels": list(vessels.values())
    }


NAVAL_NAME_KEYWORDS = (
    "NAVY", "NAVAL", "USS ", "HMS ", "HMAS ", "HMCS ",
    "PATROL", "COAST GUARD", "COASTGUARD", "WARSHIP",
    "FRIGATE", "DESTROYER", "CORVETTE", "MINESWEEP",
)

# MMSI MID -> 국가 매핑 (주요 감시 대상국)
MID_TO_COUNTRY = {
    "201": "AL", "211": "DE", "212": "CY", "215": "MT", "219": "DK",
    "220": "DK", "224": "ES", "225": "ES", "226": "FR", "227": "FR",
    "228": "FR", "229": "MT", "230": "FI", "231": "FI", "232": "GB",
    "233": "GB", "234": "GB", "235": "GB", "236": "GI", "237": "GR",
    "238": "HR", "239": "GR", "240": "GR", "241": "GR", "242": "MA",
    "243": "HU", "244": "NL", "245": "NL", "246": "NL", "247": "IT",
    "248": "MT", "249": "MT", "250": "IE", "255": "PT", "256": "MT",
    "257": "NO", "258": "NO", "259": "NO", "261": "PL", "263": "PT",
    "265": "SE", "266": "SE", "269": "CH", "270": "CZ", "271": "TR",
    "272": "UA", "273": "RU", "274": "RU", "275": "LV", "276": "EE",
    "277": "LT", "278": "SI", "279": "HR",
    "301": "AI", "303": "US", "338": "US", "366": "US", "367": "US",
    "368": "US", "369": "US", "370": "US", "371": "US",
    "401": "AF", "403": "SA", "405": "BD", "408": "BH", "410": "BT",
    "412": "CN", "413": "CN", "414": "CN", "416": "TW", "417": "LK",
    "419": "IN", "422": "IR", "423": "AZ", "425": "IQ", "428": "IL",
    "431": "JP", "432": "JP", "440": "KR", "441": "KR", "443": "PS",
    "445": "KP", "447": "KW", "450": "LB", "455": "MV", "457": "MN",
    "461": "PK", "466": "QA", "468": "SY", "470": "AE", "471": "AE",
    "472": "TJ", "473": "YE", "477": "HK",
    "501": "FR", "503": "AU", "506": "MM", "508": "BN", "510": "FM",
    "511": "PW", "512": "NZ", "514": "KH", "515": "KH", "516": "AU",
    "518": "CK", "520": "FJ", "525": "ID", "529": "KI",
    "533": "MY", "536": "MP", "538": "MH", "540": "NC", "542": "NU",
    "544": "NR", "546": "FR", "548": "PH", "553": "PG", "555": "PN",
    "557": "SB", "559": "AS", "561": "WS", "563": "SG", "564": "SG",
    "565": "SG", "566": "SG", "567": "TH", "570": "TO", "572": "TV",
    "574": "VN", "576": "VU", "577": "VU",
    "601": "ZA", "603": "AO", "605": "DZ", "607": "FR", "608": "GB",
    "609": "MU", "610": "MZ", "611": "EG", "612": "LY", "613": "ER",
    "616": "KE", "617": "TZ", "618": "DJ", "619": "MG", "620": "CM",
    "621": "TG", "622": "GM", "624": "GN", "625": "NG", "626": "SO",
    "627": "MR", "630": "GH", "631": "CI", "632": "SN", "633": "TD",
    "634": "SD", "635": "SS", "636": "LR", "637": "LR",
}


def mmsi_to_nation(mmsi):
    """MMSI에서 MID(Maritime Identification Digits)로 국적 추출"""
    if not mmsi or len(mmsi) < 3:
        return ""
    # 특수 MMSI: 99Mxxxxxx = NATO/해군 전용, 98MIDxxxx = 보조선박
    if mmsi.startswith("99"):
        return "NATO/특수"
    if mmsi.startswith("98"):
        mid3 = mmsi[2:5]
        return MID_TO_COUNTRY.get(mid3, "")
    mid3 = mmsi[:3]
    return MID_TO_COUNTRY.get(mid3, "")


def classify_vessel(v):
    """군함 식별"""
    mmsi = v.get("mmsi", "")
    nation = mmsi_to_nation(mmsi)

    # 선명 공백 정리
    ship_name_raw = v.get("ship_name") or ""
    v = {**v, "ship_name": ship_name_raw.strip(), "nation": nation}

    # 알려진 군함
    if mmsi in KNOWN_NAVAL_MMSI:
        info = KNOWN_NAVAL_MMSI[mmsi]
        return {**v, **info, "classification": "CONFIRMED_NAVAL", "confidence": "A-1"}

    # 선박 유형 35 = Military
    ship_type = v.get("ship_type")
    if ship_type == 35:
        return {**v, "classification": "PROBABLE_NAVAL", "confidence": "B-2",
                "assessment": "선박유형(Military) 기반 군함 추정"}

    # 선명 기반 군함 키워드 매칭
    name_upper = v["ship_name"].upper()
    for kw in NAVAL_NAME_KEYWORDS:
        if kw in name_upper:
            return {**v, "classification": "PROBABLE_NAVAL", "confidence": "B-3",
                    "assessment": f"선명 키워드 '{kw.strip()}' 매칭"}

    # 선박 유형 55 = Law Enforcement (해경/해양경찰)
    if ship_type == 55:
        return {**v, "classification": "GOVT_LAW_ENFORCEMENT", "confidence": "B-3",
                "assessment": "법집행 선박 (AIS type 55)"}

    # 대형 고속 선박 (80m 이상, 18kts 이상)
    # 단, 여객선(60-69), 화물선(70-79), 유조선(80-89) 제외
    length = v.get("length", 0) or 0
    speed = v.get("speed_kts", 0) or 0
    if length >= 80 and speed >= 18:
        if ship_type and 60 <= ship_type <= 89:
            pass  # 상선 - CIVILIAN 유지
        else:
            return {**v, "classification": "POSSIBLE_NAVAL", "confidence": "C-3",
                    "assessment": f"대형 고속 선박 ({length}m, {speed}kts)"}

    return {**v, "classification": "CIVILIAN"}


def collect_maritime():
    """해상 AIS 전체 수집"""
    print("\n[Maritime] == 해상 AIS 수집 시작 ==")

    if not AISSTREAM_API_KEY:
        print("[Maritime] ⚠ AISSTREAM_API_KEY 미설정 - 건너뜀")
        return {"collection_time": datetime.now(timezone.utc).isoformat(),
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
        "collection_time": datetime.now(timezone.utc).isoformat(),
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
        print(f"  {rd['regionName']}: 선박 {rd['total_vessels']}척, 군함/정부선 {len(naval)}척")

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
            if v["classification"] in ("CONFIRMED_NAVAL", "PROBABLE_NAVAL"):
                summary["alerts"].append({
                    "type": v["classification"],
                    "priority": "HIGH" if v.get("type") == "carrier" else "ELEVATED",
                    "detail": f"{v.get('name',v.get('ship_name','?'))} ({v.get('nation','?')}) - {rd['regionName']} AIS 포착",
                })

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = os.path.join(out_dir, f"maritime_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Maritime] == 완료: 스캔 {summary['total_vessels_scanned']}척, 군함 {summary['total_naval_detected']}척 ==")
    return summary


if __name__ == "__main__":
    collect_maritime()
