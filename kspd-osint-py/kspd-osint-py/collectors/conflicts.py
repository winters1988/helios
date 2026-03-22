"""
KSPD OSINT Engine - 분쟁 이벤트 수집기
1. GDELT Project (무료, 키 불필요) - 군사/분쟁 뉴스
2. ACLED (OAuth 인증) - 분쟁 이벤트 데이터
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import ACLED_EMAIL, ACLED_PASSWORD, WATCH_COUNTRIES


def _gdelt_fetch_batch(session, queries, timespan="24h", sourcelang=""):
    """GDELT 쿼리 배치 실행. 성공한 기사 목록 반환."""
    articles = []
    consecutive_fails = 0

    lang_param = f"&sourcelang={sourcelang}" if sourcelang else ""

    for q in queries:
        if consecutive_fails >= 3:
            print(f"  GDELT 연속 3회 실패 - 나머지 쿼리 건너뜀 (timespan={timespan})")
            break

        for attempt in range(2):
            try:
                url = (f"https://api.gdeltproject.org/api/v2/doc/doc?"
                       f"query={requests.utils.quote(q)}&mode=artlist"
                       f"&maxrecords=10&format=json&timespan={timespan}{lang_param}")
                resp = session.get(url, timeout=(10, 40))
                if resp.ok:
                    data = resp.json()
                    for a in data.get("articles") or []:
                        articles.append({
                            "title": a.get("title", ""),
                            "url": a.get("url", ""),
                            "source": a.get("domain", ""),
                            "date": a.get("seendate", ""),
                            "language": a.get("language", ""),
                            "query": q,
                        })
                    consecutive_fails = 0
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == 0:
                    print(f"  GDELT '{q[:30]}' 타임아웃, 재시도...")
                    time.sleep(5)
                else:
                    print(f"  GDELT '{q[:30]}' 실패 (2회 시도)")
                    consecutive_fails += 1
            except Exception as e:
                print(f"  GDELT '{q[:30]}' 실패: {e}")
                consecutive_fails += 1
                break
        time.sleep(6)

    return articles


def fetch_gdelt():
    """GDELT API - 군사/분쟁 관련 최신 뉴스 수집 (무료, 키 불필요)"""
    print("[Conflicts] GDELT 뉴스 수집...")

    # 1단: 핵심 분쟁 쿼리 (영어 우선)
    core_queries = [
        "Iran military strike",
        "Israel Iran attack",
        "Ukraine Russia frontline",
        "North Korea missile test",
        "Taiwan strait China military",
        "Houthi Red Sea ship",
    ]

    # 2단: 군사 동향 쿼리 (영어 우선)
    military_queries = [
        "carrier strike group deploy",
        "NATO exercise military",
        "US military Middle East",
        "South China Sea navy",
        "nuclear weapon threat",
    ]

    # 3단: 한국어 쿼리 (한국 매체 확보)
    korean_queries = [
        "북한 미사일 도발",
        "이란 공격 중동",
        "우크라이나 전선 러시아",
    ]

    # 4단: 공급망 특화 쿼리 (Tier 4 - 산업/원자재/물류)
    supply_chain_queries = [
        "semiconductor supply chain disruption",
        "rare earth export control China",
        "lithium cobalt price surge",
        "tungsten indium supply shortage",
        "Hormuz shipping disruption oil tanker",
        "Red Sea shipping container reroute",
        "aluminum smelter shutdown",
        "OPEC production cut oil price",
        "chip shortage automotive semiconductor",
        "critical minerals supply chain",
        "LNG supply Europe energy crisis",
        "container shipping rate freight",
        "port congestion global supply chain",
        "nickel copper price rally",
        "China export ban mineral",
    ]

    # 4단(한국어): 공급망 특화 한국어 쿼리
    supply_chain_kr_queries = [
        "반도체 공급망 차질",
        "희토류 수출 규제 중국",
        "유가 급등 원유 공급",
        "해운 운임 급등 물류",
        "핵심광물 공급망 리스크",
    ]

    session = requests.Session()

    # 1차: 핵심 쿼리 영어
    all_articles = _gdelt_fetch_batch(session, core_queries, "24h", sourcelang="english")
    print(f"  GDELT 핵심(영어): {len(all_articles)}건")

    # 2차: 군사 동향 영어
    mil_articles = _gdelt_fetch_batch(session, military_queries, "24h", sourcelang="english")
    all_articles.extend(mil_articles)
    print(f"  GDELT 군사동향(영어): {len(mil_articles)}건")

    # 3차: 한국어 쿼리
    kr_articles = _gdelt_fetch_batch(session, korean_queries, "24h", sourcelang="korean")
    all_articles.extend(kr_articles)
    print(f"  GDELT 한국어: {len(kr_articles)}건")

    # 4차: 공급망 특화 쿼리 (Tier 4)
    sc_articles = _gdelt_fetch_batch(session, supply_chain_queries, "24h", sourcelang="english")
    all_articles.extend(sc_articles)
    print(f"  GDELT 공급망(영어): {len(sc_articles)}건")

    sc_kr_articles = _gdelt_fetch_batch(session, supply_chain_kr_queries, "24h", sourcelang="korean")
    all_articles.extend(sc_kr_articles)
    print(f"  GDELT 공급망(한국어): {len(sc_kr_articles)}건")

    # 5차: 영어 5건 미만이면 전체 언어 보조
    en_count = len([a for a in all_articles if a.get("language") == "English"])
    if en_count < 5:
        print(f"  GDELT 영어 {en_count}건 부족 - 전체 언어 보조 수집")
        supplement = _gdelt_fetch_batch(session, core_queries[:3], "24h")
        all_articles.extend(supplement)

    # 5차: 여전히 5건 미만이면 48h로 확대
    if len(all_articles) < 5:
        print(f"  GDELT 24h 결과 {len(all_articles)}건 - 48h로 확대 재시도")
        fallback = _gdelt_fetch_batch(session, core_queries[:4], "48h", sourcelang="english")
        all_articles.extend(fallback)

    session.close()

    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    # 관련성 필터: 군사/안보 키워드가 제목에 포함된 기사 우선
    RELEVANCE_KEYWORDS = (
        "military", "missile", "attack", "strike", "war", "nuclear", "navy",
        "bomb", "drone", "defense", "weapon", "soldier", "troops", "combat",
        "carrier", "fighter", "submarine", "sanction", "conflict", "tension",
        "artillery", "casualt", "frontline", "invasion", "ceasefire",
        "軍", "攻擊", "飛彈", "戰", "核", "國防", "공격", "미사일", "전쟁", "군사",
        "военн", "удар", "ракет", "оборон", "атак", "фронт",
        # Tier 4: 공급망/원자재/물류 키워드
        "supply chain", "semiconductor", "rare earth", "lithium", "cobalt",
        "tungsten", "shipping", "freight", "container", "oil price", "opec",
        "smelter", "export control", "critical mineral", "chip shortage",
        "port", "lng", "nickel", "copper", "aluminum",
        "공급망", "반도체", "희토류", "해운", "운임", "유가", "핵심광물",
    )

    def relevance_score(article):
        title_lower = article.get("title", "").lower()
        lang = article.get("language", "")
        score = 0
        # 영어 우선
        if lang == "English":
            score += 2
        elif lang == "Korean":
            score += 1
        # 군사 키워드
        for kw in RELEVANCE_KEYWORDS:
            if kw.lower() in title_lower:
                score += 3
                break
        return score

    # 관련성 순 정렬, 비관련 기사는 하위로
    unique.sort(key=relevance_score, reverse=True)

    relevant = [a for a in unique if relevance_score(a) >= 3]
    others = [a for a in unique if relevance_score(a) < 3]
    final = relevant + others[:max(5, 30 - len(relevant))]

    # ── 교차검증: 동일 사건을 보도하는 독립 소스 수 계산 ──
    final = _cross_validate_headlines(final)

    print(f"  GDELT: {len(unique)}건 수집, 관련성 필터 후 {len(relevant)}건 우선")
    return final


# ── 교차검증용 사건 클러스터 키워드 ──
EVENT_CLUSTERS = [
    {"event": "US-Iran conflict", "keywords": ["iran", "attack", "strike", "war", "이란", "공격", "打击", "伊朗", "иран", "удар"]},
    {"event": "Iran drone boat", "keywords": ["drone boat", "tanker", "hormuz", "호르무즈", "oil tanker"]},
    {"event": "Ukraine-Russia frontline", "keywords": ["ukraine", "frontline", "russia", "우크라이나", "전선", "乌克兰", "украин", "фронт"]},
    {"event": "North Korea missile", "keywords": ["north korea", "missile", "김정은", "북한", "미사일", "朝鲜", "导弹"]},
    {"event": "Israel-Lebanon", "keywords": ["israel", "lebanon", "이스라엘", "레바논", "以色列", "黎巴嫩"]},
    {"event": "Hormuz strait closure", "keywords": ["hormuz", "strait", "closure", "escort", "호르무즈", "봉쇄"]},
    {"event": "French military deploy", "keywords": ["rafale", "charles de gaulle", "frégate", "french", "프랑스"]},
    {"event": "Nuclear weapon", "keywords": ["nuclear", "iaea", "핵", "核", "ядерн"]},
    {"event": "Iran warship sunk", "keywords": ["warship sank", "warship sunk", "이란 군함", "침몰"]},
    {"event": "South China Sea", "keywords": ["south china sea", "남중국해", "南海"]},
    # Tier 4: 공급망 특화 클러스터
    {"event": "Semiconductor supply chain", "keywords": ["semiconductor", "chip shortage", "반도체", "芯片", "nxp", "nvidia", "tsmc", "삼성전자"]},
    {"event": "Rare earth export control", "keywords": ["rare earth", "희토류", "稀土", "tungsten", "indium", "gallium", "germanium", "export control"]},
    {"event": "Energy price surge", "keywords": ["oil price", "opec", "brent", "wti", "유가", "lng", "natural gas", "energy crisis"]},
    {"event": "Shipping disruption", "keywords": ["shipping disruption", "container", "freight", "scfi", "bdi", "해운", "운임", "port congestion"]},
    {"event": "Critical minerals", "keywords": ["lithium", "cobalt", "nickel", "리튬", "코발트", "핵심광물", "critical mineral", "battery supply"]},
]


def _cross_validate_headlines(articles):
    """동일 사건을 보도하는 독립 소스 수를 계산하여 교차검증 정보 추가"""
    # 각 기사를 이벤트 클러스터에 매핑
    for art in articles:
        title_lower = art.get("title", "").lower()
        art["matched_events"] = []
        for cluster in EVENT_CLUSTERS:
            for kw in cluster["keywords"]:
                if kw.lower() in title_lower:
                    art["matched_events"].append(cluster["event"])
                    break

    # 각 이벤트별 독립 소스(domain) 수 계산
    event_sources = {}
    for art in articles:
        source = art.get("source", "")
        for evt in art.get("matched_events", []):
            if evt not in event_sources:
                event_sources[evt] = set()
            event_sources[evt].add(source)

    # 결과를 각 기사에 첨부
    for art in articles:
        best_count = 0
        best_event = ""
        for evt in art.get("matched_events", []):
            cnt = len(event_sources.get(evt, set()))
            if cnt > best_count:
                best_count = cnt
                best_event = evt
        art["cross_source_count"] = best_count
        art["corroborated"] = best_count >= 3  # 3개 이상 독립 소스면 교차검증 됨
        art["event_cluster"] = best_event
        # matched_events는 내부용이므로 제거
        del art["matched_events"]

    # 교차검증 통계 로그
    corr_count = len([a for a in articles if a.get("corroborated")])
    print(f"  GDELT 교차검증: {corr_count}/{len(articles)}건 복수소스 확인")

    return articles


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

    seven_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
            events = data.get("data") or []
            print(f"  ACLED {theater}: {len(events)}건")
            return {"theater": theater, "events": events}
        elif resp.status_code == 403:
            print(f"  ACLED {theater}: 접근 거부 (403) - Research 레벨 이상 계정 필요 (https://acleddata.com/myacled-faqs)")
            return None
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
    print("\n[Conflicts] == 분쟁 이벤트 수집 시작 ==")

    # GDELT (항상 가능)
    gdelt_articles = fetch_gdelt()

    # ACLED (계정 있을 때만)
    acled_results = []
    token = get_acled_token()
    if token:
        print("[Conflicts] ACLED 토큰 발급 성공")
        acled_failed = False
        for theater, countries in WATCH_COUNTRIES.items():
            if acled_failed:
                break
            print(f"[Conflicts] ACLED 수집: {theater}")
            result = fetch_acled(token, countries, theater)
            if result is None and not acled_failed:
                acled_failed = True
                print("[Conflicts] ⚠ ACLED 접근 실패 - 나머지 theater 건너뜀, GDELT만 사용")
            else:
                acled_results.append(result)
            time.sleep(2)
    else:
        print("[Conflicts] ⚠ ACLED 미설정 - GDELT만 사용")

    # 분석
    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
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
    out_path = os.path.join(out_dir, f"conflicts_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Conflicts] == 완료: ACLED {summary['event_statistics']['total_events']}건, GDELT {len(gdelt_articles)}건 ==")
    return summary


if __name__ == "__main__":
    collect_conflicts()
