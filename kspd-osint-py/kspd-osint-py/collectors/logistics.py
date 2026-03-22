"""
KSPD OSINT Engine — 해운 물류 데이터 수집기
컨테이너 운임지수(SCFI/BDI), 주요 항만 현황

데이터 소스:
- GDELT 물류 뉴스 (운임/항만 뉴스 자동 수집)
- 정적 참조 데이터 + 뉴스 기반 변동 감지
- 향후: Freightos Baltic Index API, IMF PortWatch API 연동 예정
"""

import requests
import json
import os
import time
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ══════════════════════════════════════════════════
# 주요 해운 지수 참조 (GDELT 뉴스에서 실시간 업데이트)
# ══════════════════════════════════════════════════

SHIPPING_INDICES = {
    "SCFI": {
        "name_kr": "상하이컨테이너운임지수",
        "name_en": "Shanghai Containerized Freight Index",
        "description": "상하이 출발 글로벌 컨테이너 운임 종합지수",
        "gdelt_queries": ["SCFI Shanghai freight index", "Shanghai container freight rate"],
    },
    "BDI": {
        "name_kr": "발틱운임지수",
        "name_en": "Baltic Dry Index",
        "description": "건화물 해운 운임 지수 (벌크선)",
        "gdelt_queries": ["Baltic Dry Index shipping", "BDI freight rate"],
    },
    "FBX": {
        "name_kr": "프레이토스 글로벌 컨테이너 운임지수",
        "name_en": "Freightos Baltic Index",
        "description": "글로벌 40피트 컨테이너 운임",
        "gdelt_queries": ["Freightos container rate", "global container shipping cost"],
    },
    "WCI": {
        "name_kr": "드류리 세계컨테이너지수",
        "name_en": "Drewry World Container Index",
        "description": "주요 8개 항로 40피트 컨테이너 운임",
        "gdelt_queries": ["Drewry container index", "world container shipping index"],
    },
}

# 주요 감시 항만 (공급망 핵심 허브)
WATCH_PORTS = {
    # 중동/GCC
    "jebel_ali": {"name_kr": "제벨알리 (두바이)", "name_en": "Jebel Ali", "country": "UAE", "region": "중동"},
    "king_abdulaziz": {"name_kr": "킹압둘아지즈 (담맘)", "name_en": "King Abdulaziz Port", "country": "Saudi Arabia", "region": "중동"},
    "hamad": {"name_kr": "하마드 (도하)", "name_en": "Hamad Port", "country": "Qatar", "region": "중동"},
    "sohar": {"name_kr": "소하르 (오만)", "name_en": "Sohar Port", "country": "Oman", "region": "중동"},
    "bandar_abbas": {"name_kr": "반다르아바스 (이란)", "name_en": "Bandar Abbas", "country": "Iran", "region": "중동"},

    # 아시아
    "shanghai": {"name_kr": "상하이", "name_en": "Shanghai", "country": "China", "region": "아시아"},
    "singapore": {"name_kr": "싱가포르", "name_en": "Singapore", "country": "Singapore", "region": "아시아"},
    "busan": {"name_kr": "부산", "name_en": "Busan", "country": "South Korea", "region": "아시아"},
    "kaohsiung": {"name_kr": "가오슝", "name_en": "Kaohsiung", "country": "Taiwan", "region": "아시아"},

    # 유럽
    "rotterdam": {"name_kr": "로테르담", "name_en": "Rotterdam", "country": "Netherlands", "region": "유럽"},
    "hamburg": {"name_kr": "함부르크", "name_en": "Hamburg", "country": "Germany", "region": "유럽"},

    # 홍해/수에즈
    "suez": {"name_kr": "수에즈 운하", "name_en": "Suez Canal", "country": "Egypt", "region": "홍해"},
    "aden": {"name_kr": "아덴", "name_en": "Aden", "country": "Yemen", "region": "홍해"},
}


def _fetch_logistics_news(session):
    """GDELT에서 해운/물류 관련 최신 뉴스 수집"""
    articles = []

    queries = [
        "container shipping freight rate surge",
        "port congestion delay",
        "Suez Canal disruption",
        "Red Sea shipping reroute Houthi",
        "Hormuz strait tanker oil shipping",
        "Baltic Dry Index BDI",
        "SCFI Shanghai freight",
        "global supply chain logistics disruption",
        "port shutdown strike",
        "해운 운임 급등",
        "항만 적체 물류",
        "수에즈 운하 통행",
    ]

    for q in queries:
        lang_param = "&sourcelang=korean" if any(ord(c) > 0x1100 for c in q) else "&sourcelang=english"
        try:
            url = (f"https://api.gdeltproject.org/api/v2/doc/doc?"
                   f"query={requests.utils.quote(q)}&mode=artlist"
                   f"&maxrecords=5&format=json&timespan=72h{lang_param}")
            resp = session.get(url, timeout=(10, 30))
            if resp.ok:
                data = resp.json()
                for a in data.get("articles") or []:
                    articles.append({
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("domain", ""),
                        "date": a.get("seendate", ""),
                        "query": q,
                        "category": "logistics",
                    })
        except Exception:
            pass
        time.sleep(1)

    # 중복 제거
    seen = set()
    unique = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    print(f"  GDELT 물류뉴스: {len(unique)}건 수집")
    return unique


def _extract_port_status_from_news(articles):
    """뉴스에서 항만 상태 키워드 추출"""
    port_mentions = {}

    for port_id, port_info in WATCH_PORTS.items():
        keywords = [port_info["name_en"].lower(), port_info["name_kr"]]
        count = 0
        relevant_headlines = []

        for art in articles:
            title_lower = art.get("title", "").lower()
            for kw in keywords:
                if kw.lower() in title_lower:
                    count += 1
                    relevant_headlines.append(art["title"][:100])
                    break

        if count > 0:
            # 부정적 키워드 감지
            negative_kw = ["disruption", "delay", "congestion", "shutdown", "strike",
                           "closure", "blocked", "attack", "차질", "폐쇄", "적체", "파업"]
            is_disrupted = any(
                kw in art.get("title", "").lower()
                for art in articles
                for kw in negative_kw
                if any(pk.lower() in art.get("title", "").lower() for pk in keywords)
            )

            port_mentions[port_id] = {
                "port_name": port_info["name_kr"],
                "port_name_en": port_info["name_en"],
                "country": port_info["country"],
                "region": port_info["region"],
                "news_mentions": count,
                "status": "DISRUPTED" if is_disrupted else "MENTIONED",
                "headlines": relevant_headlines[:3],
            }

    return port_mentions


def _generate_alerts(port_status, news_articles):
    """물류 알림 생성"""
    alerts = []

    # 항만 차질 알림
    for port_id, status in port_status.items():
        if status["status"] == "DISRUPTED":
            alerts.append({
                "type": "PORT_DISRUPTION",
                "priority": "HIGH",
                "port": status["port_name"],
                "detail": f"{status['port_name']} ({status['country']}) 항만 운영 차질 보도 {status['news_mentions']}건",
            })

    # 주요 해운 뉴스 급증 감지
    logistics_news_count = len(news_articles)
    if logistics_news_count > 30:
        alerts.append({
            "type": "LOGISTICS_NEWS_SURGE",
            "priority": "ELEVATED",
            "detail": f"물류/해운 관련 뉴스 급증: {logistics_news_count}건 (72시간)",
        })

    # 홍해/수에즈/호르무즈 차질 뉴스 감지
    critical_route_kw = ["suez", "hormuz", "red sea", "houthi", "수에즈", "호르무즈", "홍해"]
    critical_count = sum(
        1 for a in news_articles
        if any(kw in a.get("title", "").lower() for kw in critical_route_kw)
    )
    if critical_count >= 5:
        alerts.append({
            "type": "CRITICAL_ROUTE_DISRUPTION",
            "priority": "HIGH",
            "detail": f"주요 해상 교통로(홍해/수에즈/호르무즈) 관련 뉴스 {critical_count}건 — 항로 우회/차질 가능성",
        })

    return alerts


def collect_logistics():
    """전체 해운 물류 데이터 수집"""
    print("\n[Logistics] ══ 해운 물류 데이터 수집 시작 ══")

    session = requests.Session()

    # GDELT 물류 뉴스 수집
    news_articles = _fetch_logistics_news(session)

    session.close()

    # 항만 상태 추출
    port_status = _extract_port_status_from_news(news_articles)

    # 알림
    alerts = _generate_alerts(port_status, news_articles)

    # 해운 지수 참조 정보
    indices_info = {}
    for idx_id, idx_data in SHIPPING_INDICES.items():
        indices_info[idx_id] = {
            "name_kr": idx_data["name_kr"],
            "name_en": idx_data["name_en"],
            "description": idx_data["description"],
            "note": "GDELT 뉴스 기반 간접 모니터링 (API 연동 예정)",
        }

    # 지역별 항만 요약
    region_summary = {}
    for port_id, status in port_status.items():
        region = status["region"]
        if region not in region_summary:
            region_summary[region] = {"total_ports_mentioned": 0, "disrupted": 0, "ports": []}
        region_summary[region]["total_ports_mentioned"] += 1
        if status["status"] == "DISRUPTED":
            region_summary[region]["disrupted"] += 1
        region_summary[region]["ports"].append(status["port_name"])

    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "sources": ["GDELT"],
        "classification": "UNCLASSIFIED // OSINT",
        "shipping_indices": indices_info,
        "port_status": port_status,
        "region_summary": region_summary,
        "logistics_news": news_articles[:20],
        "total_news": len(news_articles),
        "alerts": alerts,
    }

    # 저장
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"logistics_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Logistics] ══ 완료: 뉴스 {len(news_articles)}건, 항만 {len(port_status)}개 감지, 알림 {len(alerts)}건 ══")
    return summary


if __name__ == "__main__":
    collect_logistics()
