"""
KSPD OSINT Engine - 환율 데이터 수집기
원/달러, 원/위안, 원/엔 등 주요 환율 실시간 수집

데이터 소스:
- Primary: ExchangeRate-API (무료: 일 1500회)
- Fallback: Open Exchange Rates
"""

import requests
import json
import os
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    EXCHANGE_RATE_API_KEY,
    FOREX_WATCHLIST,
    FOREX_ALERT_THRESHOLDS,
)


def _fetch_exchange_rate_api(session):
    """ExchangeRate-API에서 환율 수집 (무료: 일 1500회)"""
    if not EXCHANGE_RATE_API_KEY:
        return None

    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
        resp = session.get(url, timeout=15)
        if resp.ok:
            data = resp.json()
            if data.get("result") == "success":
                rates = data.get("conversion_rates", {})
                results = {}
                for currency, info in FOREX_WATCHLIST.items():
                    if currency in rates:
                        results[currency] = {
                            "rate": rates[currency],
                            "base": "USD",
                            "name_kr": info["name_kr"],
                            "name_en": info["name_en"],
                            "source": "exchangerate-api.com",
                        }
                print(f"  ExchangeRate-API: {len(results)}개 환율 수집")
                return results
            else:
                print(f"  ExchangeRate-API 오류: {data.get('error-type', 'unknown')}")
        else:
            print(f"  ExchangeRate-API HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ExchangeRate-API 오류: {e}")

    return None


def _fetch_open_exchange_rates(session):
    """Open Exchange Rates에서 환율 수집 (무료 Fallback)"""
    try:
        # 무료 tier는 app_id 불필요한 latest endpoint
        url = "https://open.er-api.com/v6/latest/USD"
        resp = session.get(url, timeout=15)
        if resp.ok:
            data = resp.json()
            if data.get("result") == "success":
                rates = data.get("rates", {})
                results = {}
                for currency, info in FOREX_WATCHLIST.items():
                    if currency in rates:
                        results[currency] = {
                            "rate": rates[currency],
                            "base": "USD",
                            "name_kr": info["name_kr"],
                            "name_en": info["name_en"],
                            "source": "open.er-api.com",
                        }
                print(f"  Open ER API (fallback): {len(results)}개 환율 수집")
                return results
        else:
            print(f"  Open ER API HTTP {resp.status_code}")
    except Exception as e:
        print(f"  Open ER API 오류: {e}")

    return None


def _load_previous_forex(output_dir):
    """이전 환율 데이터 로드 (변동률 계산용)"""
    try:
        files = sorted(
            [f for f in os.listdir(output_dir) if f.startswith("forex_") and f.endswith(".json")],
            reverse=True,
        )
        if files:
            with open(os.path.join(output_dir, files[0]), "r", encoding="utf-8") as f:
                prev = json.load(f)
                return prev.get("rates", {}), prev.get("collection_time", "")
    except Exception:
        pass
    return {}, ""


def _calculate_changes(current_rates, previous_rates):
    """환율 변동률 계산"""
    for currency, data in current_rates.items():
        prev = previous_rates.get(currency, {})
        prev_rate = prev.get("rate", 0)
        curr_rate = data.get("rate", 0)

        if prev_rate and curr_rate:
            change = curr_rate - prev_rate
            change_pct = round((change / prev_rate) * 100, 2)
            data["prev_rate"] = prev_rate
            data["change"] = round(change, 4)
            data["change_pct"] = change_pct
        else:
            data["prev_rate"] = None
            data["change"] = None
            data["change_pct"] = None

    return current_rates


def _generate_alerts(rates):
    """환율 급변 알림 생성"""
    alerts = []

    for currency, data in rates.items():
        change_pct = data.get("change_pct")
        if change_pct is None:
            continue

        threshold = FOREX_ALERT_THRESHOLDS.get(currency, FOREX_ALERT_THRESHOLDS.get("DEFAULT", 2.0))
        abs_change = abs(change_pct)

        if abs_change >= threshold:
            direction = "약세(달러 강세)" if change_pct > 0 else "강세(달러 약세)"
            name = data.get("name_kr", currency)

            priority = "HIGH" if abs_change >= threshold * 2 else "ELEVATED"
            alerts.append({
                "type": "FOREX_ALERT",
                "priority": priority,
                "currency": currency,
                "detail": (
                    f"{name} {direction}: {data['rate']} "
                    f"(전일 대비 {'+' if change_pct > 0 else ''}{change_pct}%)"
                ),
                "change_pct": change_pct,
            })

    return sorted(alerts, key=lambda x: abs(x.get("change_pct", 0)), reverse=True)


def collect_forex():
    """전체 환율 데이터 수집"""
    print("\n[Forex] == 환율 데이터 수집 시작 ==")

    session = requests.Session()
    rates = None
    source_used = ""

    # 1차: ExchangeRate-API
    rates = _fetch_exchange_rate_api(session)
    if rates:
        source_used = "ExchangeRate-API"

    # 2차: Fallback - Open ER API (키 불필요)
    if not rates:
        print("  ExchangeRate-API 실패 - Open ER API로 fallback")
        rates = _fetch_open_exchange_rates(session)
        if rates:
            source_used = "Open ER API"

    session.close()

    if not rates:
        print("[Forex] == 수집 실패: 모든 API 응답 없음 ==")
        return {
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "classification": "UNCLASSIFIED // OSINT",
            "total_currencies": 0,
            "rates": {},
            "alerts": [],
        }

    # 이전 데이터 대비 변동률
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    prev_rates, prev_time = _load_previous_forex(out_dir)
    rates = _calculate_changes(rates, prev_rates)

    # 알림
    alerts = _generate_alerts(rates)

    # 주요 환율 요약 로그
    for cur in ["KRW", "CNY", "JPY"]:
        if cur in rates:
            r = rates[cur]
            chg = f" ({'+' if (r.get('change_pct') or 0) > 0 else ''}{r.get('change_pct', 'N/A')}%)" if r.get("change_pct") is not None else ""
            print(f"  {r['name_kr']}: {r['rate']}{chg}")

    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "sources": [source_used],
        "classification": "UNCLASSIFIED // OSINT",
        "previous_collection": prev_time,
        "total_currencies": len(rates),
        "rates": rates,
        "alerts": alerts,
    }

    # 저장
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"forex_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Forex] == 완료: {len(rates)}개 환율, 알림 {len(alerts)}건 ==")
    return summary


if __name__ == "__main__":
    collect_forex()
