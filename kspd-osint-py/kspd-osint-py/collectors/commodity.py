"""
KSPD OSINT Engine — 원자재/에너지 가격 수집기
1. 무료 API 활용: 유가(WTI/브렌트), 비철금속, 귀금속, 에너지
2. 공급망 인텔리전스 Threat Brief 연동용

데이터 소스 (우선순위):
1. OilPriceAPI — 브렌트유 (무료: 일 100회)
2. MetalPriceAPI — 귀금속 XAU/XAG/XPT/XPD (무료: 월 100회)
3. Yahoo Finance (yfinance) — WTI, 천연가스, 비철금속 등 (무료, 키 불필요)
4. Commodities API — 종합 원자재 (유료 전환 시 활성화)
"""

import requests
import json
import os
import time
from datetime import datetime, timedelta, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    COMMODITY_API_KEY,
    COMMODITY_WATCHLIST,
    COMMODITY_ALERT_THRESHOLDS,
)


def _fetch_commodities_api(session, symbols):
    """commodities-api.com에서 원자재 가격 수집 (무료 tier: 월 100회)"""
    if not COMMODITY_API_KEY:
        return None

    results = {}
    base_url = "https://commodities-api.com/api/latest"

    try:
        # 무료 tier: base=USD, symbols=comma separated
        symbol_str = ",".join(symbols)
        resp = session.get(
            base_url,
            params={
                "access_key": COMMODITY_API_KEY,
                "base": "USD",
                "symbols": symbol_str,
            },
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data.get("success"):
                rates = data.get("data", {}).get("rates", {})
                for sym, rate in rates.items():
                    if rate and rate > 0:
                        # commodities-api는 1 USD = X commodity 형태
                        # 원자재 가격은 역수: 1 commodity = X USD
                        price_usd = round(1.0 / rate, 2) if rate != 0 else 0
                        results[sym] = {
                            "price_usd": price_usd,
                            "raw_rate": rate,
                            "source": "commodities-api.com",
                        }
                print(f"  Commodities API: {len(results)}개 가격 수집")
                return results
            else:
                print(f"  Commodities API 오류: {data.get('error', {}).get('info', 'unknown')}")
        else:
            print(f"  Commodities API HTTP {resp.status_code}")
    except Exception as e:
        print(f"  Commodities API 오류: {e}")

    return None


def _fetch_oil_price_api(session):
    """OilPriceAPI.com에서 유가 수집 (무료 tier: 일 100회)"""
    from config.settings import OIL_PRICE_API_KEY
    if not OIL_PRICE_API_KEY:
        return None

    results = {}
    base_url = "https://api.oilpriceapi.com/v1/prices/latest"

    try:
        resp = session.get(
            base_url,
            headers={"Authorization": f"Token {OIL_PRICE_API_KEY}"},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            price_data = data.get("data", {})
            if price_data:
                results["OIL_BRENT"] = {
                    "price_usd": price_data.get("price", 0),
                    "currency": "USD/bbl",
                    "source": "oilpriceapi.com",
                    "created_at": price_data.get("created_at", ""),
                }
                print(f"  OilPriceAPI: 브렌트유 ${price_data.get('price', 0)}/bbl")
                return results
        else:
            print(f"  OilPriceAPI HTTP {resp.status_code}")
    except Exception as e:
        print(f"  OilPriceAPI 오류: {e}")

    return None


def _fetch_metals_api(session):
    """metalpriceapi.com에서 금속 가격 수집 (무료 tier: 귀금속만 지원)"""
    from config.settings import METALS_API_KEY
    if not METALS_API_KEY:
        return None

    results = {}
    base_url = "https://api.metalpriceapi.com/v1/latest"

    # 무료 tier는 귀금속(XAU/XAG/XPT/XPD)만 지원
    # 비철금속(XCU/ALU/NI 등)은 유료 — 별도 시도하여 가능한 것만 수집
    free_metals = ["XAU", "XAG", "XPT", "XPD"]
    paid_metals = ["XCU", "ALU", "NI", "ZNC", "TIN", "LCO"]

    def _query_metals(symbols, label):
        try:
            resp = session.get(
                base_url,
                params={
                    "api_key": METALS_API_KEY,
                    "base": "USD",
                    "currencies": ",".join(symbols),
                },
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                if data.get("success"):
                    rates = data.get("rates", {})
                    fetched = 0
                    for sym, rate in rates.items():
                        # USD 접두사 제거 (USDXAU → XAU)
                        clean_sym = sym.replace("USD", "") if sym.startswith("USD") else sym
                        if clean_sym in symbols and rate and rate > 0:
                            price_usd = round(1.0 / rate, 4) if rate != 0 else 0
                            results[clean_sym] = {
                                "price_usd": price_usd,
                                "raw_rate": rate,
                                "source": "metalpriceapi.com",
                            }
                            fetched += 1
                    return fetched
                else:
                    err = data.get("error", {}).get("message", "unknown")
                    print(f"  MetalPriceAPI {label}: {err}")
            else:
                print(f"  MetalPriceAPI {label} HTTP {resp.status_code}")
        except Exception as e:
            print(f"  MetalPriceAPI {label} 오류: {e}")
        return 0

    # 1차: 무료 귀금속
    free_count = _query_metals(free_metals, "귀금속")

    # 2차: 유료 비철금속 시도 (실패해도 무시)
    paid_count = _query_metals(paid_metals, "비철금속")

    total = free_count + paid_count
    if total > 0:
        print(f"  MetalPriceAPI: {total}개 금속 가격 수집 (귀금속 {free_count}, 비철 {paid_count})")
        return results

    return None


# ══════════════════════════════════════════════════
# Yahoo Finance — 무료, 키 불필요
# COMMODITY_WATCHLIST 심볼 → Yahoo Finance 선물 심볼 매핑
# ══════════════════════════════════════════════════

YAHOO_SYMBOL_MAP = {
    # 에너지
    "WTI":   {"yf": "CL=F",  "unit_note": "USD/bbl"},
    "BRENT": {"yf": "BZ=F",  "unit_note": "USD/bbl"},
    "NG":    {"yf": "NG=F",  "unit_note": "USD/MMBtu"},
    # COAL: Yahoo Finance에 석탄 선물 없음 — 수집 불가

    # 비철금속
    "XCU":   {"yf": "HG=F",  "unit_note": "USD/lb",  "to_ton": 2204.62},  # lb → 톤 환산
    "ALU":   {"yf": "ALI=F", "unit_note": "USD/ton"},
    "ZNC":   {"yf": "ZNC=F", "unit_note": "USD/ton"},

    # 귀금속 (MetalPriceAPI fallback)
    "XAU":   {"yf": "GC=F",  "unit_note": "USD/oz"},
    "XAG":   {"yf": "SI=F",  "unit_note": "USD/oz"},
    "XPT":   {"yf": "PL=F",  "unit_note": "USD/oz"},
    "XPD":   {"yf": "PA=F",  "unit_note": "USD/oz"},

    # 핵심광물 — 직접 선물 없음, ETF 프록시
    "LCO":   {"yf": "LIT",   "unit_note": "ETF price", "proxy": True,
              "proxy_note": "Global X Lithium & Battery Tech ETF (직접 리튬 가격 아님)"},
}


def _fetch_yahoo_finance(needed_symbols):
    """Yahoo Finance에서 원자재 선물/ETF 가격 수집 (무료, 키 불필요)"""
    try:
        import yfinance as yf
    except ImportError:
        print("  Yahoo Finance: yfinance 미설치 (pip install yfinance)")
        return None

    results = {}
    for our_sym in needed_symbols:
        mapping = YAHOO_SYMBOL_MAP.get(our_sym)
        if not mapping:
            continue

        yf_sym = mapping["yf"]
        try:
            ticker = yf.Ticker(yf_sym)
            info = ticker.fast_info
            price = info.get("lastPrice", 0) or info.get("regularMarketPrice", 0)
            prev_close = info.get("previousClose", 0) or info.get("regularMarketPreviousClose", 0)

            if not price or price <= 0:
                continue

            # 구리: lb → 톤 환산 (선택)
            display_price = price
            if mapping.get("to_ton"):
                display_price = round(price * mapping["to_ton"], 2)

            change_pct = None
            if prev_close and prev_close > 0:
                raw_pct = (price - prev_close) / prev_close * 100
                if not (raw_pct != raw_pct):  # NaN check
                    change_pct = round(raw_pct, 2)

            entry = {
                "price_usd": round(display_price, 4),
                "source": "yahoo_finance",
                "yf_symbol": yf_sym,
                "yf_raw_price": round(price, 4),
                "yf_prev_close": round(prev_close, 4) if prev_close else None,
                "yf_change_pct": change_pct,
            }

            if mapping.get("proxy"):
                entry["proxy"] = True
                entry["proxy_note"] = mapping.get("proxy_note", "")

            results[our_sym] = entry

        except Exception as e:
            print(f"  Yahoo Finance {our_sym} ({yf_sym}): {e}")
            continue

    if results:
        print(f"  Yahoo Finance: {len(results)}개 원자재 가격 수집")
    return results if results else None


def _load_previous_prices(output_dir):
    """이전 수집 데이터에서 가격 로드 (변동률 계산용)"""
    try:
        files = sorted(
            [f for f in os.listdir(output_dir) if f.startswith("commodity_") and f.endswith(".json")],
            reverse=True,
        )
        if files:
            with open(os.path.join(output_dir, files[0]), "r", encoding="utf-8") as f:
                prev = json.load(f)
                return prev.get("prices", {}), prev.get("collection_time", "")
    except Exception:
        pass
    return {}, ""


def _calculate_changes(current_prices, previous_prices):
    """가격 변동률 계산. Yahoo Finance 데이터는 자체 전일대비를 가지고 있음."""
    for symbol, data in current_prices.items():
        # Yahoo Finance 소스는 자체 전일대비(yf_change_pct) 사용
        if data.get("source") == "yahoo_finance" and data.get("yf_change_pct") is not None:
            yf_pct = data["yf_change_pct"]
            yf_prev = data.get("yf_prev_close", 0)
            data["prev_price_usd"] = data.get("yf_prev_close")
            data["change_pct"] = yf_pct
            data["change_usd"] = round(data["price_usd"] - (data.get("yf_prev_close") or 0), 2) if data.get("yf_prev_close") else None
            continue

        # 기존 API 소스: 이전 수집 데이터 대비 변동률
        prev = previous_prices.get(symbol, {})
        prev_price = prev.get("price_usd", 0)
        curr_price = data.get("price_usd", 0)

        if prev_price and curr_price:
            change = curr_price - prev_price
            change_pct = round((change / prev_price) * 100, 2)
            data["prev_price_usd"] = prev_price
            data["change_usd"] = round(change, 2)
            data["change_pct"] = change_pct
        else:
            data["prev_price_usd"] = None
            data["change_usd"] = None
            data["change_pct"] = None

    return current_prices


def _generate_alerts(prices):
    """급등/급락 알림 생성"""
    alerts = []

    for symbol, data in prices.items():
        change_pct = data.get("change_pct")
        if change_pct is None:
            continue

        threshold = COMMODITY_ALERT_THRESHOLDS.get(symbol, COMMODITY_ALERT_THRESHOLDS.get("DEFAULT", 5.0))
        abs_change = abs(change_pct)

        if abs_change >= threshold:
            direction = "급등" if change_pct > 0 else "급락"
            name = COMMODITY_WATCHLIST.get(symbol, {}).get("name_kr", symbol)
            unit = COMMODITY_WATCHLIST.get(symbol, {}).get("unit", "")

            priority = "HIGH" if abs_change >= threshold * 2 else "ELEVATED"
            alerts.append({
                "type": "COMMODITY_PRICE_ALERT",
                "priority": priority,
                "symbol": symbol,
                "detail": (
                    f"{name} {direction}: ${data['price_usd']}{unit} "
                    f"(전일 대비 {'+' if change_pct > 0 else ''}{change_pct}%)"
                ),
                "change_pct": change_pct,
            })

    return sorted(alerts, key=lambda x: abs(x.get("change_pct", 0)), reverse=True)


def collect_commodity():
    """원자재/에너지 가격 전체 수집"""
    print("\n[Commodity] ══ 원자재/에너지 가격 수집 시작 ══")

    session = requests.Session()
    all_prices = {}
    sources_used = []

    # 1차: OilPriceAPI (유가 전문)
    oil_data = _fetch_oil_price_api(session)
    if oil_data:
        all_prices.update(oil_data)
        sources_used.append("OilPriceAPI")

    # 2차: Commodities API (종합 원자재)
    commodity_symbols = list(COMMODITY_WATCHLIST.keys())
    comm_data = _fetch_commodities_api(session, commodity_symbols)
    if comm_data:
        # OilPriceAPI 데이터가 없는 심볼만 추가
        for sym, data in comm_data.items():
            if sym not in all_prices:
                all_prices[sym] = data
        sources_used.append("CommoditiesAPI")

    # 3차: MetalPriceAPI (금속 특화)
    metals_data = _fetch_metals_api(session)
    if metals_data:
        for sym, data in metals_data.items():
            if sym not in all_prices:
                all_prices[sym] = data
        sources_used.append("MetalPriceAPI")

    session.close()

    # 4차: Yahoo Finance — 아직 수집되지 않은 심볼 보충 (무료, 키 불필요)
    watchlist_symbols = set(COMMODITY_WATCHLIST.keys())
    collected_symbols = set(all_prices.keys())
    # OIL_BRENT는 BRENT와 같은 데이터이므로 BRENT도 수집된 것으로 처리
    if "OIL_BRENT" in collected_symbols:
        collected_symbols.add("BRENT")
    needed = watchlist_symbols - collected_symbols
    # Yahoo Finance에서 매핑이 있는 심볼만 필터
    yf_candidates = [s for s in needed if s in YAHOO_SYMBOL_MAP]
    if yf_candidates:
        yf_data = _fetch_yahoo_finance(yf_candidates)
        if yf_data:
            all_prices.update(yf_data)
            sources_used.append("Yahoo Finance")
    # 이미 수집된 심볼도 Yahoo Finance에 있으면 yf_change_pct(전일대비)를 보강
    for sym in collected_symbols:
        if sym in YAHOO_SYMBOL_MAP and sym not in (yf_candidates or []):
            # 기존 데이터에 yf 변동률만 보강 (가격은 기존 API 우선)
            pass

    # 가격 메타데이터 추가
    for symbol, data in all_prices.items():
        # OIL_BRENT는 OilPriceAPI 전용 키 → BRENT 메타데이터 사용
        lookup_key = "BRENT" if symbol == "OIL_BRENT" else symbol
        info = COMMODITY_WATCHLIST.get(lookup_key, {})
        data["name_kr"] = info.get("name_kr", symbol)
        data["name_en"] = info.get("name_en", symbol)
        data["category"] = info.get("category", "기타")
        data["unit"] = info.get("unit", "")

    # 이전 가격 대비 변동률 계산
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    prev_prices, prev_time = _load_previous_prices(out_dir)
    all_prices = _calculate_changes(all_prices, prev_prices)

    # 알림 생성
    alerts = _generate_alerts(all_prices)

    # 카테고리별 요약
    category_summary = {}
    for symbol, data in all_prices.items():
        cat = data.get("category", "기타")
        if cat not in category_summary:
            category_summary[cat] = []
        category_summary[cat].append({
            "symbol": symbol,
            "name_kr": data.get("name_kr", symbol),
            "price_usd": data.get("price_usd", 0),
            "unit": data.get("unit", ""),
            "change_pct": data.get("change_pct"),
        })

    # 결과 조합
    summary = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "sources": sources_used,
        "classification": "UNCLASSIFIED // OSINT",
        "previous_collection": prev_time,
        "total_commodities": len(all_prices),
        "prices": all_prices,
        "category_summary": category_summary,
        "alerts": alerts,
    }

    # 저장
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"commodity_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Commodity] ══ 완료: {len(all_prices)}개 원자재, 알림 {len(alerts)}건 ══")
    return summary


if __name__ == "__main__":
    collect_commodity()
