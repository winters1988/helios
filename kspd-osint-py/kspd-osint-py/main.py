"""
KSPD OSINT Engine — 메인 실행 파이프라인
전체 수집 → 종합 분석 → AI 브리핑 생성

사용법:
    python main.py              # 전체 실행
    python main.py --aviation   # 항공만
    python main.py --maritime   # 해상만
    python main.py --conflicts  # 분쟁만
    python main.py --thermal    # 열이상만
    python main.py --commodity  # 원자재 가격만
    python main.py --forex      # 환율만
    python main.py --logistics  # 해운 물류만
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timezone

from collectors.aviation import collect_aviation
from collectors.maritime import collect_maritime
from collectors.conflicts import collect_conflicts
from collectors.thermal import collect_thermal
from collectors.commodity import collect_commodity
from collectors.forex import collect_forex
from collectors.logistics import collect_logistics
from config.settings import GEMINI_API_KEY

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _build_corroboration_analysis(data, data_summary):
    """센서 데이터와 뉴스 보도 간 불일치를 정량 분석"""
    headlines = data.get("conflicts", {}).get("gdelt_headlines", [])

    # 이벤트 클러스터별 뉴스 강도 계산
    event_news_intensity = {}
    for h in headlines:
        evt = h.get("event_cluster", "")
        if evt:
            if evt not in event_news_intensity:
                event_news_intensity[evt] = {"count": 0, "sources": set(), "corroborated": False}
            event_news_intensity[evt]["count"] += 1
            event_news_intensity[evt]["sources"].add(h.get("source", ""))
            if h.get("corroborated"):
                event_news_intensity[evt]["corroborated"] = True

    # 센서 데이터 요약
    sensor_mil_aircraft = data_summary["aviation"]["total_military"]
    sensor_naval = data_summary["maritime"]["total_naval"]
    sensor_conflicts = data_summary["conflicts"]["total_events"]
    sensor_hotspots = data_summary["thermal"]["total_hotspots"]
    mil_alerts = data_summary["thermal"]["military_alerts"]

    # 지역별 센서-뉴스 매칭
    theater_analysis = []

    # 중동
    me_news = sum(v["count"] for k, v in event_news_intensity.items()
                  if k in ("US-Iran conflict", "Iran drone boat", "Israel-Lebanon",
                           "Hormuz strait closure", "Iran warship sunk"))
    me_corr = any(v["corroborated"] for k, v in event_news_intensity.items()
                  if k in ("US-Iran conflict", "Iran drone boat", "Israel-Lebanon",
                           "Hormuz strait closure", "Iran warship sunk"))
    me_sources = set()
    for k, v in event_news_intensity.items():
        if k in ("US-Iran conflict", "Iran drone boat", "Israel-Lebanon",
                 "Hormuz strait closure", "Iran warship sunk"):
            me_sources.update(v["sources"])

    me_sensor_evidence = []
    iran_hotspots = next((r["hotspots"] for r in data_summary["thermal"]["regions"]
                          if r["name"] == "이란"), 0)
    if iran_hotspots > 0:
        me_sensor_evidence.append(f"이란 열점 {iran_hotspots}건")
    if mil_alerts:
        for a in mil_alerts:
            me_sensor_evidence.append(f"{a['facility']} 인근 열점 {a['nearby']}건 (최근접 {a['closest_km']}km)")

    theater_analysis.append({
        "theater": "중동",
        "news_intensity": me_news,
        "independent_sources": len(me_sources),
        "cross_validated": me_corr,
        "sensor_evidence": me_sensor_evidence if me_sensor_evidence else ["직접적 교전 증거 미탐지"],
        "gap_assessment": "HIGH" if me_news >= 5 and not me_sensor_evidence else
                          "MODERATE" if me_news >= 3 else "LOW",
        "gap_explanation": (
            "대규모 교전 보도에도 군용기/군함 미탐지는 "
            "작전 중 트랜스폰더·AIS 소거가 일반적이므로 구조적으로 예상되는 현상. "
            "FIRMS 열점은 48시간 누적이며 정밀타격은 탐지 한계 이하일 수 있음."
        ) if me_news >= 5 else ""
    })

    # 인도태평양
    ip_news = sum(v["count"] for k, v in event_news_intensity.items()
                  if k in ("North Korea missile", "South China Sea"))
    ip_sources = set()
    for k, v in event_news_intensity.items():
        if k in ("North Korea missile", "South China Sea"):
            ip_sources.update(v["sources"])

    nk_hotspots = next((r["hotspots"] for r in data_summary["thermal"]["regions"]
                        if r["name"] == "북한"), 0)
    ip_sensor = []
    if nk_hotspots > 0:
        ip_sensor.append(f"북한 열점 {nk_hotspots}건")

    theater_analysis.append({
        "theater": "인도태평양",
        "news_intensity": ip_news,
        "independent_sources": len(ip_sources),
        "cross_validated": any(v.get("corroborated") for k, v in event_news_intensity.items()
                               if k in ("North Korea missile", "South China Sea")),
        "sensor_evidence": ip_sensor if ip_sensor else ["특이 군사 활동 미탐지"],
        "gap_assessment": "MODERATE" if ip_news >= 3 else "LOW",
    })

    # 유럽
    eu_news = sum(v["count"] for k, v in event_news_intensity.items()
                  if k in ("Ukraine-Russia frontline", "French military deploy"))
    eu_sources = set()
    for k, v in event_news_intensity.items():
        if k in ("Ukraine-Russia frontline", "French military deploy"):
            eu_sources.update(v["sources"])

    ua_hotspots = next((r["hotspots"] for r in data_summary["thermal"]["regions"]
                        if r["name"] == "우크라이나"), 0)
    eu_sensor = []
    if ua_hotspots > 0:
        eu_sensor.append(f"우크라이나 열점 {ua_hotspots}건")
    if sensor_naval > 0:
        eu_sensor.append(f"군함 {sensor_naval}척 탐지")

    theater_analysis.append({
        "theater": "유럽",
        "news_intensity": eu_news,
        "independent_sources": len(eu_sources),
        "cross_validated": any(v.get("corroborated") for k, v in event_news_intensity.items()
                               if k in ("Ukraine-Russia frontline",)),
        "sensor_evidence": eu_sensor if eu_sensor else ["특이 군사 활동 미탐지"],
        "gap_assessment": "MODERATE" if eu_news >= 3 and not eu_sensor else "LOW",
    })

    # 전체 교차검증 통계
    total_corroborated = len([h for h in headlines if h.get("corroborated")])
    total_single_source = len([h for h in headlines if not h.get("corroborated")])

    return {
        "headline_reliability": {
            "total_headlines": len(headlines),
            "cross_validated": total_corroborated,
            "single_source_only": total_single_source,
            "note": f"전체 {len(headlines)}건 중 {total_corroborated}건이 3개 이상 독립 소스에서 확인됨"
        },
        "theater_corroboration": theater_analysis,
    }


def generate_briefing(data):
    """Gemini API로 ICD 203 형식 한국어 브리핑 생성"""
    if not GEMINI_API_KEY:
        print("[Briefing] GEMINI_API_KEY 미설정 — 자동 요약으로 대체")
        return auto_briefing(data)

    # 수집 데이터 요약 (프롬프트 토큰 절약)
    # 항공 지역별 요약 (군용기 0인 지역도 전체 항공기 수 포함)
    av_regions_summary = []
    for r in data.get("aviation", {}).get("regions", []):
        entry = {"name": r["regionName"], "total": r["total_aircraft"], "mil": r["military_detected"]}
        if r.get("military_detected", 0) > 0:
            entry["notable"] = [{"cs": a["callsign"], "country": a["origin_country"], "assess": a["assessment"]}
                                for a in r.get("military_aircraft", [])[:3]]
        av_regions_summary.append(entry)

    data_summary = {
        "aviation": {
            "total_military": data.get("aviation", {}).get("total_military_detected", 0),
            "total_aircraft_scanned": sum(r.get("total_aircraft", 0) for r in data.get("aviation", {}).get("regions", [])),
            "regions": av_regions_summary,
        },
        "maritime": {
            "total_naval": data.get("maritime", {}).get("total_naval_detected", 0),
            "total_vessels_scanned": data.get("maritime", {}).get("total_vessels_scanned", 0),
            "vessels": [{
                "name": v["name"], "nation": v.get("nation", ""), "region": r["regionName"],
                "classification": v["classification"], "assessment": v.get("assessment", "")
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
                "name": r["region"], "hotspots": r["total_hotspots"],
                "seasonal_note": r.get("seasonal_note", ""),
            } for r in data.get("thermal", {}).get("regions", []) if r.get("total_hotspots", 0) > 0],
            "military_alerts": [{
                "facility": a["facility"], "nearby": a["total_nearby"],
                "high_confidence": a["high_confidence"], "closest_km": a["closest_km"]
            } for a in data.get("thermal", {}).get("military_proximity_alerts", [])],
        },
        "headlines": [
            {
                "title": a["title"], "source": a.get("source", ""),
                "lang": a.get("language", ""),
                "corroborated": a.get("corroborated", False),
                "cross_source_count": a.get("cross_source_count", 0),
                "event_cluster": a.get("event_cluster", ""),
            }
            for a in data.get("conflicts", {}).get("gdelt_headlines", [])[:15]
        ],
        # ── 공급망 인텔리전스 (신규) ──
        "commodity": {
            "total": data.get("commodity", {}).get("total_commodities", 0),
            "sources": data.get("commodity", {}).get("sources", []),
            "prices": {
                sym: {
                    "name_kr": d.get("name_kr", sym),
                    "price_usd": d.get("price_usd", 0),
                    "unit": d.get("unit", ""),
                    "change_pct": d.get("change_pct"),
                    "category": d.get("category", ""),
                }
                for sym, d in data.get("commodity", {}).get("prices", {}).items()
            },
            "alerts": data.get("commodity", {}).get("alerts", [])[:5],
        },
        "forex": {
            "total": data.get("forex", {}).get("total_currencies", 0),
            "rates": {
                cur: {
                    "name_kr": d.get("name_kr", cur),
                    "rate": d.get("rate", 0),
                    "change_pct": d.get("change_pct"),
                }
                for cur, d in data.get("forex", {}).get("rates", {}).items()
            },
            "alerts": data.get("forex", {}).get("alerts", [])[:3],
        },
        "logistics": {
            "total_news": data.get("logistics", {}).get("total_news", 0),
            "port_status": {
                pid: {
                    "name": d.get("port_name", ""),
                    "status": d.get("status", ""),
                    "region": d.get("region", ""),
                    "mentions": d.get("news_mentions", 0),
                }
                for pid, d in data.get("logistics", {}).get("port_status", {}).items()
            },
            "region_summary": data.get("logistics", {}).get("region_summary", {}),
            "alerts": data.get("logistics", {}).get("alerts", [])[:3],
            "top_news": [
                {"title": n.get("title", ""), "source": n.get("source", "")}
                for n in data.get("logistics", {}).get("logistics_news", [])[:5]
            ],
        },
    }

    # ── 센서-뉴스 불일치 분석 (data_summary 구성 후 계산) ──
    corroboration = _build_corroboration_analysis(data, data_summary)
    data_summary["corroboration_analysis"] = corroboration

    today_mmdd = datetime.now(timezone.utc).strftime("%m%d")
    today_full = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""당신은 KSPD THE ONE 유현인텔리전스의 수석 OSINT 분석관입니다.
아래 수집 데이터를 기반으로 **한국어** 일일 정보 브리핑을 작성하세요.

오늘 날짜: {today_full}
형식: ICD 203 정보 분석 표준 준용
분류: UNCLASSIFIED // OSINT

=== 수집 데이터 ===
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

=== 출처 신뢰도 등급 (반드시 준수) ===
- **1차 출처 (센서 데이터):** aviation, maritime, thermal 수치 → 직접 관측 데이터. 사실로 기술 가능.
- **2차 출처 (뉴스 헤드라인):** gdelt_headlines → 언론 보도일 뿐 확인된 사실 아님.
  "~로 보도되었다", "~라는 보도가 있다" 등 인용 형식으로만 기술.
  뉴스 헤드라인을 센서 데이터처럼 단정적으로 기술하지 말 것.
- 센서 데이터와 뉴스 간 불일치가 있으면, 이를 정보 공백에서 명시적으로 다룰 것.
- 센서 데이터가 0인 분야는 "탐지되지 않음"으로 기술. 없는 활동을 추론하지 말 것.

=== 수집 환경 및 센서 한계 (정보 공백 작성 시 반드시 참고) ===
- 수집 시각: {datetime.now(timezone.utc).strftime("%H:%M")} UTC
- **항공 (OpenSky):** 수집 시점 스냅샷. 군용기는 대부분 ADS-B 트랜스폰더를 끄고 비행하므로
  OSINT로 탐지 가능한 것은 훈련/이동 중 트랜스폰더 활성 항공기에 한정됨.
  군용기 0대는 "군사 활동 없음"이 아닌 "탐지 가능한 활동 없음"을 의미.
- **해상 (AIS):** 지역당 30초 스냅샷. 군함은 작전 중 AIS를 소거하는 것이 일반적.
  해역 내 군함 미탐지는 부재를 의미하지 않음.
- **열점 (FIRMS):** 최근 48시간 누적. 계절별 농업 소각(3~4월 이란/한반도)이 열점의 주요 원인.
  지역별 seasonal_note 필드를 참고하여 열점 원인을 맥락적으로 설명할 것.
  군사시설 인근 열점만 군사적 의미를 부여.
- **뉴스 (GDELT):** 자동 수집이며, 특정 국가 매체에 편중될 수 있음.
  각 헤드라인에 cross_source_count(독립 소스 수)와 corroborated(3개+ 소스 확인) 필드 포함.
  corroborated=true 보도는 신뢰도 높음, false는 단일 소스 보도로 신뢰도 낮게 평가.

=== 센서-뉴스 불일치 분석 지침 (반드시 준수) ===
- corroboration_analysis 데이터에 지역별 뉴스 강도 vs 센서 증거 비교가 포함됨.
- gap_assessment가 HIGH인 지역은 정보 공백에서 반드시 다룰 것.
- 뉴스 보도량이 많으나 센서 탐지가 없는 경우, 두 가지 해석을 제시:
  (1) 군사 작전 중 센서 소거(트랜스폰더/AIS OFF)로 인한 구조적 탐지 한계
  (2) 보도 과장 또는 미확인 정보 유통 가능성
- cross_validated=true인 사건은 복수 독립 소스에서 확인되었으므로
  센서 미탐지에도 발생 가능성을 높게(Likely 이상) 평가.
- single_source_only 보도는 확인 시까지 Unlikely~Roughly Even Chance로 유보적 평가.

=== 작성 지침 ===
1. 제목: "일일 정보 브리핑 #{today_mmdd}"
2. 핵심 판단 3~5개, 각 항목에 ICD 203 확률 용어 사용
   (Almost Certain/Very Likely/Likely/Roughly Even Chance/Unlikely/Very Unlikely/Remote)
3. 전구별 상황: 중동, 인도태평양, 유럽 (각 2~3문단)
   - 센서 데이터(항공/해상/열점)와 뉴스 보도를 구분하여 기술
4. **공급망 인텔리전스** (Supply Chain Intelligence) — 신규 섹션
   - 원자재/에너지: commodity 데이터에서 주요 가격 변동, 급등/급락 알림 기술
   - 환율 동향: forex 데이터에서 주요 통화 변동, 공급망 영향 분석
   - 해운/물류: logistics 데이터에서 항만 차질, 주요 해운 뉴스, 운임 동향
   - 가격 데이터는 수치를 정확히 기재 (예: "브렌트유 $85.30/bbl, 전일 대비 +3.2%")
   - 공급망 뉴스(GDELT Tier 4)와 원자재 가격 변동 간 상관관계 분석
5. 정보 공백 (Intelligence Gaps)
6. 전망 (향후 24~72시간)
7. 요점정리 (Executive Summary) — 브리핑 맨 마지막에 배치
   - 오늘의 핵심 사항을 5~7개 bullet point로 간결하게 요약
   - 각 bullet은 1줄 이내, 수치와 팩트 중심
   - 의사결정자가 30초 안에 상황을 파악할 수 있도록 작성
   - 원자재/환율 주요 변동 사항 반드시 포함

톤: 간결, 객관적. 사실과 평가를 명확히 구분. 2,500~4,000자.
한국어로 작성하세요."""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 16384}
            },
            timeout=120,
        )
        if resp.ok:
            text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if text:
                return {"generated_by": "Gemini + KSPD OSINT Desk", "briefing_text": text,
                        "generated_at": datetime.now(timezone.utc).isoformat(), "icd203": True}
        print(f"[Briefing] Gemini 응답 오류: {resp.status_code}")
    except Exception as e:
        print(f"[Briefing] Gemini 오류: {e}")

    return auto_briefing(data)


def auto_briefing(data):
    """AI 없을 때 데이터 기반 자동 브리핑"""
    now = datetime.now(timezone.utc)
    lines = []
    lines.append(f"# 일일 정보 브리핑 #{now.strftime('%m%d')}")
    lines.append(f"\n**분류:** UNCLASSIFIED // OSINT")
    lines.append(f"**작성:** {now.strftime('%Y-%m-%d %H:%M')} UTC | KSPD OSINT Desk")
    lines.append(f"**출처:** OpenSky, AISStream, GDELT, NASA FIRMS, CommodityAPI, ExchangeRate, GDELT-Logistics\n")
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
    lines.append(f"- 열점 {th_total}건 탐지, 군사시설 인근 {th_mil}건\n")

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

    # 공급망 인텔리전스
    lines.append("\n## 공급망 인텔리전스\n")

    # 원자재
    comm = data.get("commodity", {})
    if comm.get("prices"):
        lines.append("### 원자재/에너지 가격\n")
        for sym, pdata in comm.get("prices", {}).items():
            name = pdata.get("name_kr", sym)
            price = pdata.get("price_usd", 0)
            unit = pdata.get("unit", "")
            chg = pdata.get("change_pct")
            chg_str = f" ({'+' if chg > 0 else ''}{chg}%)" if chg is not None else ""
            lines.append(f"- {name}: ${price}{unit}{chg_str}")
        for alert in comm.get("alerts", [])[:3]:
            lines.append(f"  **[{alert.get('priority','')}]** {alert.get('detail','')}")

    # 환율
    fx = data.get("forex", {})
    if fx.get("rates"):
        lines.append("\n### 환율\n")
        for cur, rdata in fx.get("rates", {}).items():
            name = rdata.get("name_kr", cur)
            rate = rdata.get("rate", 0)
            chg = rdata.get("change_pct")
            chg_str = f" ({'+' if chg > 0 else ''}{chg}%)" if chg is not None else ""
            lines.append(f"- {name}: {rate}{chg_str}")

    # 물류
    logi = data.get("logistics", {})
    if logi.get("port_status"):
        lines.append("\n### 해운/물류\n")
        for pid, pstatus in logi.get("port_status", {}).items():
            status_kr = "차질" if pstatus.get("status") == "DISRUPTED" else "언급"
            lines.append(f"- {pstatus.get('port_name', pid)} ({pstatus.get('country','')}): {status_kr} — 뉴스 {pstatus.get('news_mentions',0)}건")
        for alert in logi.get("alerts", [])[:3]:
            lines.append(f"  **[{alert.get('priority','')}]** {alert.get('detail','')}")

    # 요점정리
    lines.append("\n## 요점정리 (Executive Summary)\n")
    lines.append(f"- 군용기 {av.get('total_military_detected', 0)}대 탐지")
    lines.append(f"- 군함/정부선 {mt.get('total_naval_detected', 0)}척 식별 (스캔 {mt.get('total_vessels_scanned', 0)}척)")
    lines.append(f"- 분쟁 이벤트 {cf.get('total_events', 0)}건, 사상자 {cf.get('total_fatalities', 0)}명 (7일간)")
    lines.append(f"- 열점 {th_total}건, 군사시설 인근 {th_mil}건")
    lines.append(f"- 주요 알림 {len(all_alerts)}건")
    gdelt_count = len(data.get("conflicts", {}).get("gdelt_headlines", []))
    lines.append(f"- GDELT 뉴스 {gdelt_count}건 수집")

    lines.append(f"\n---\n*공개 출처 정보(OSINT) 기반 자동 생성. 기밀 정보 미포함.*")

    text = "\n".join(lines)
    return {"generated_by": "KSPD OSINT Desk (Auto)", "briefing_text": text,
            "generated_at": datetime.now(timezone.utc).isoformat(), "icd203": False}


def main():
    start = time.time()
    print("╔══════════════════════════════════════════════╗")
    print("║  KSPD THE ONE — OSINT Collection Engine      ║")
    print("║  Global Military Intelligence Pipeline       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"시작: {datetime.now(timezone.utc).isoformat()}\n")

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

    if run_all or "--commodity" in args:
        try:
            data["commodity"] = collect_commodity()
        except Exception as e:
            print(f"[!] Commodity 실패: {e}")

    if run_all or "--forex" in args:
        try:
            data["forex"] = collect_forex()
        except Exception as e:
            print(f"[!] Forex 실패: {e}")

    if run_all or "--logistics" in args:
        try:
            data["logistics"] = collect_logistics()
        except Exception as e:
            print(f"[!] Logistics 실패: {e}")

    # AI 브리핑
    print("\n━━━ AI 브리핑 생성 ━━━")
    briefing = generate_briefing(data)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
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
        "last_run": datetime.now(timezone.utc).isoformat(),
        "duration_sec": elapsed,
        "aviation_mil": data.get("aviation", {}).get("total_military_detected", 0),
        "maritime_naval": data.get("maritime", {}).get("total_naval_detected", 0),
        "conflicts_events": data.get("conflicts", {}).get("event_statistics", {}).get("total_events", 0),
        "thermal_hotspots": data.get("thermal", {}).get("statistics", {}).get("total_hotspots", 0),
        "commodity_count": data.get("commodity", {}).get("total_commodities", 0),
        "forex_count": data.get("forex", {}).get("total_currencies", 0),
        "logistics_news": data.get("logistics", {}).get("total_news", 0),
        "alerts": sum(len(data.get(k, {}).get("alerts", []))
                      for k in ("aviation", "maritime", "conflicts", "thermal", "commodity", "forex", "logistics")),
        "briefing": md_path,
    }
    with open(os.path.join(OUTPUT_DIR, "latest_status.json"), "w") as f:
        json.dump(status, f, indent=2)

    print(f"\n╔══════════════════════════════════════════════╗")
    print(f"║  완료 ({elapsed}초)                            ║")
    print(f"╚══════════════════════════════════════════════╝")
    print(f"군용기: {status['aviation_mil']}대 | 군함: {status['maritime_naval']}척")
    print(f"분쟁: {status['conflicts_events']}건 | 열점: {status['thermal_hotspots']}건")
    print(f"원자재: {status['commodity_count']}개 | 환율: {status['forex_count']}개 | 물류뉴스: {status['logistics_news']}건")
    print(f"알림: {status['alerts']}건")
    print(f"브리핑: {md_path}")


if __name__ == "__main__":
    main()
