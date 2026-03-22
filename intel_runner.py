"""KSPD OSINT 수집 엔진 연동 모듈"""

import sys
import os
import re
import json
import threading
from datetime import datetime

KSPD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "kspd-osint-py", "kspd-osint-py")
BRIEFING_DIR = os.path.join(KSPD_PATH, "output")
SCHEDULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intel_schedule.json")
PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intel_pdf")

FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"   # Malgun Gothic (한국어)
FONT_BOLD  = r"C:\Windows\Fonts\malgunbd.ttf"

_jobs = {}
_lock = threading.Lock()


# ─── KSPD path ────────────────────────────────────────────────────────

def _ensure_kspd_path():
    if KSPD_PATH not in sys.path:
        sys.path.insert(0, KSPD_PATH)


# ─── Jobs ─────────────────────────────────────────────────────────────

def get_jobs():
    with _lock:
        return list(_jobs.values())


def get_job(job_id):
    with _lock:
        return _jobs.get(job_id)


MODULES = {
    "aviation":  ("collectors.aviation",  "collect_aviation"),
    "maritime":  ("collectors.maritime",  "collect_maritime"),
    "conflicts": ("collectors.conflicts", "collect_conflicts"),
    "thermal":   ("collectors.thermal",   "collect_thermal"),
    "commodity": ("collectors.commodity", "collect_commodity"),
    "forex":     ("collectors.forex",     "collect_forex"),
    "logistics": ("collectors.logistics", "collect_logistics"),
}

MODULE_LABELS = {
    "aviation":  "항공 (OpenSky)",
    "maritime":  "해상 (AIS)",
    "conflicts": "분쟁 (GDELT/ACLED)",
    "thermal":   "열점 (NASA FIRMS)",
    "commodity": "원자재 가격",
    "forex":     "환율",
    "logistics": "해운 물류",
}


# ─── Collection ────────────────────────────────────────────────────────

def _log(job, msg):
    """수집 로그를 job에 추가"""
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    job["logs"].append(entry)
    print(f"[Intel] {msg}")


def _run_collection(job_id: str, modules: list):
    job = _jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now().isoformat()

    try:
        _ensure_kspd_path()
        import importlib
        from main import generate_briefing

        run_all = not modules or "all" in modules
        data = {}

        for name, (mod_path, func_name) in MODULES.items():
            if not (run_all or name in modules):
                continue
            label = MODULE_LABELS.get(name, name)
            job["current"] = f"{label} 수집 중..."
            _log(job, f"{label} 수집 시작")
            try:
                mod = importlib.import_module(mod_path)
                importlib.reload(mod)
                result = getattr(mod, func_name)()
                data[name] = result
                # 수집 결과 요약 로그
                if isinstance(result, dict):
                    items = result.get("total_military_detected") or result.get("total_naval_detected") or \
                            result.get("total_commodities") or result.get("total_currencies") or \
                            result.get("event_statistics", {}).get("total_events") or \
                            result.get("statistics", {}).get("total_hotspots") or 0
                    alerts = len(result.get("alerts", []))
                    _log(job, f"{label} 완료: 데이터 {items}건, 알림 {alerts}건")
                else:
                    _log(job, f"{label} 완료")
            except Exception as e:
                job["errors"].append(f"{name}: {str(e)}")
                _log(job, f"{label} 실패: {e}")

        job["current"] = "AI 브리핑 생성 중..."
        _log(job, "Gemini AI 브리핑 생성 시작")
        briefing = generate_briefing(data)
        _log(job, "브리핑 생성 완료")

        os.makedirs(BRIEFING_DIR, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        md_path  = os.path.join(BRIEFING_DIR, f"briefing_{ts}.md")
        json_path = os.path.join(BRIEFING_DIR, f"briefing_{ts}.json")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(briefing["briefing_text"])
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(briefing, f, ensure_ascii=False, indent=2)

        # 벡터 DB 인덱싱
        job["current"] = "벡터 DB 인덱싱 중..."
        _log(job, "벡터 DB 인덱싱 시작")
        try:
            import vector_store
            vec_result = vector_store.index_intel_briefing(
                briefing["briefing_text"], ts, data
            )
            job["vector_result"] = vec_result
            _log(job, f"벡터 인덱싱 완료: {vec_result}")
        except Exception as e:
            _log(job, f"벡터 인덱싱 실패: {e}")
            job["vector_result"] = {"error": str(e)}

        stats = {
            "aviation_mil":     data.get("aviation", {}).get("total_military_detected", 0),
            "maritime_naval":   data.get("maritime", {}).get("total_naval_detected", 0),
            "conflicts_events": data.get("conflicts", {}).get("event_statistics", {}).get("total_events", 0),
            "thermal_hotspots": data.get("thermal", {}).get("statistics", {}).get("total_hotspots", 0),
            "alerts": sum(len(data.get(k, {}).get("alerts", [])) for k in data),
        }
        with open(os.path.join(BRIEFING_DIR, "latest_status.json"), "w") as f:
            json.dump({**stats, "last_run": datetime.utcnow().isoformat(),
                       "briefing": f"briefing_{ts}.json"}, f, indent=2)

        # PDF 생성
        pdf_name = f"briefing_{ts}.pdf"
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        os.makedirs(PDF_DIR, exist_ok=True)
        try:
            job["current"] = "PDF 생성 중..."
            _log(job, "PDF 생성 시작")
            generate_pdf(briefing["briefing_text"], pdf_path, ts)
            briefing["pdf_file"] = pdf_name
            _log(job, f"PDF 생성 완료: {pdf_name}")
        except Exception as e:
            pdf_name = None
            _log(job, f"PDF 생성 실패: {e}")

        job["status"] = "done"
        job["finished_at"] = datetime.now().isoformat()
        job["briefing_file"] = f"briefing_{ts}.json"
        job["pdf_file"] = pdf_name
        job["stats"] = stats
        job["current"] = "완료"

        _send_telegram(briefing["briefing_text"], stats, pdf_name)

    except Exception as e:
        job["status"] = "error"
        job["finished_at"] = datetime.now().isoformat()
        job["current"] = f"오류: {e}"
        job["errors"].append(str(e))
        print(f"[Intel] 수집 오류: {e}")


def start_collection(modules: list = None) -> str:
    job_id = f"intel_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "status": "pending",
            "modules": modules or ["all"],
            "started_at": None, "finished_at": None,
            "current": "대기 중...", "errors": [],
            "stats": None, "briefing_file": None, "pdf_file": None,
            "vector_result": None, "logs": [],
        }
    threading.Thread(target=_run_collection, args=(job_id, modules or []), daemon=True).start()
    return job_id


# ─── PDF 생성 ─────────────────────────────────────────────────────────

def generate_pdf(briefing_text: str, output_path: str, ts: str = "") -> str:
    from fpdf import FPDF

    # 날짜 파싱
    try:
        doc_dt = datetime.strptime(ts, "%Y%m%d_%H%M") if ts else datetime.utcnow()
    except Exception:
        doc_dt = datetime.utcnow()
    doc_date_str = doc_dt.strftime("%Y년 %m월 %d일  %H:%M UTC")
    doc_id = doc_dt.strftime("%Y%m%d-%H%M")

    class BriefingPDF(FPDF):
        def header(self):
            # 상단 네이비 바
            self.set_fill_color(15, 23, 42)
            self.rect(0, 0, 210, 12, style="F")
            self.set_y(2)
            self.set_font("MalgunB", size=7.5)
            self.set_text_color(148, 163, 184)
            self.cell(100, 8, "KSPD OSINT  ·  UNCLASSIFIED // FOR OFFICIAL USE ONLY", align="L")
            self.set_text_color(100, 116, 139)
            self.cell(0, 8, f"DOC-{doc_id}", align="R")
            self.set_y(14)

        def footer(self):
            self.set_y(-14)
            self.set_draw_color(203, 213, 225)
            self.line(15, self.get_y(), 195, self.get_y())
            self.ln(1.5)
            self.set_font("Malgun", size=7.5)
            self.set_text_color(100, 116, 139)
            self.cell(130, 6, "공개 출처 정보(OSINT) 기반 자동 생성. 기밀 정보 미포함.", align="L")
            self.cell(0, 6, f"{self.page_no()} / {{nb}}", align="R")

    pdf = BriefingPDF()
    pdf.alias_nb_pages()
    pdf.set_margins(15, 18, 15)
    pdf.set_auto_page_break(auto=True, margin=18)

    # 폰트 등록
    if os.path.exists(FONT_PATH):
        pdf.add_font("Malgun", fname=FONT_PATH)
    if os.path.exists(FONT_BOLD):
        pdf.add_font("MalgunB", fname=FONT_BOLD)
        pdf.add_font("Malgun", style="B", fname=FONT_BOLD)

    # ── 표지 페이지 ──────────────────────────────────────
    pdf.add_page()
    pdf.set_y(35)

    # 분류 배너
    pdf.set_fill_color(15, 23, 42)
    pdf.set_font("MalgunB", size=9)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 10, "UNCLASSIFIED  //  OPEN SOURCE INTELLIGENCE", align="C", fill=True)
    pdf.ln(16)

    # 메인 타이틀
    pdf.set_font("MalgunB", size=26)
    pdf.set_text_color(15, 23, 42)
    pdf.multi_cell(0, 12, "OSINT 인텔리전스", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("MalgunB", size=18)
    pdf.set_text_color(51, 65, 85)
    pdf.multi_cell(0, 10, "일일 정보 브리핑", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # 구분선
    pdf.set_draw_color(30, 58, 138)
    pdf.set_line_width(1.2)
    pdf.line(35, pdf.get_y(), 175, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(10)

    # 부제목
    pdf.set_font("Malgun", size=12)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 8, f"Daily Intelligence Briefing  ·  {doc_date_str}", align="C")
    pdf.ln(6)
    pdf.set_font("Malgun", size=10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 7, "KSPD THE ONE  ·  유현인텔리전스  ·  OSINT Desk", align="C")
    pdf.ln(20)

    # 정보 박스
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(30, pdf.get_y(), 150, 38, style="FD")
    pdf.set_y(pdf.get_y() + 6)
    rows = [
        ("출처",    "OpenSky · AISStream · GDELT · NASA FIRMS · CommodityAPI"),
        ("분류",    "UNCLASSIFIED // OSINT"),
        ("작성",    "KSPD OSINT 자동 수집 시스템  +  Gemini AI"),
        ("문서 ID", f"DOC-{doc_id}"),
    ]
    for label, val in rows:
        pdf.set_x(36)
        pdf.set_font("MalgunB", size=8.5)
        pdf.set_text_color(30, 58, 138)
        pdf.cell(22, 7, label, align="L")
        pdf.set_font("Malgun", size=8.5)
        pdf.set_text_color(51, 65, 85)
        pdf.cell(0, 7, val)
        pdf.ln()

    # 하단 경고
    pdf.set_y(-40)
    pdf.set_fill_color(254, 249, 195)
    pdf.set_draw_color(234, 179, 8)
    pdf.rect(15, pdf.get_y(), 180, 10, style="FD")
    pdf.set_font("Malgun", size=8)
    pdf.set_text_color(133, 77, 14)
    pdf.cell(0, 10, "  [!]  본 문서는 공개 출처 정보에 기반하며 기밀 정보를 포함하지 않습니다.", align="L")

    # ── 본문 페이지 ──────────────────────────────────────
    pdf.add_page()

    LM = 15   # left margin
    RM = 195  # right edge (210 - 15)
    W  = RM - LM  # 180mm full width

    def clean_md(text: str) -> str:
        """마크다운 인라인 마크업 제거 후 텍스트만 반환"""
        t = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        t = re.sub(r'\*([^*]+)\*',     r'\1', t)
        t = re.sub(r'`([^`]+)`',       r'\1', t)
        t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
        return t.strip()

    def is_bold_line(text: str) -> bool:
        """줄 전체가 ** ** 로 감싸진 경우 또는 볼드 비율이 높은 경우"""
        if text.startswith("**") and text.endswith("**"):
            return True
        bold_chars = sum(len(m.group(1)) for m in re.finditer(r'\*\*([^*]+)\*\*', text))
        return bold_chars > len(text) * 0.5

    def render_text(text: str, size: float, color: tuple,
                    x: float = LM, w: float = W, lh_factor: float = 0.58):
        """multi_cell 기반 안전한 텍스트 렌더링"""
        clean = clean_md(text)
        if not clean:
            return
        font = "MalgunB" if is_bold_line(text) else "Malgun"
        pdf.set_font(font, size=size)
        pdf.set_text_color(*color)
        pdf.set_x(x)
        pdf.multi_cell(w, size * lh_factor, clean, new_x="LMARGIN", new_y="NEXT")

    lines = briefing_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1

        if not stripped:
            pdf.ln(2.5)
            continue

        try:
            # H1
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = clean_md(stripped[2:])
                pdf.set_font("MalgunB", size=16)
                pdf.set_text_color(15, 23, 42)
                pdf.set_x(LM)
                pdf.multi_cell(W, 9, title, new_x="LMARGIN", new_y="NEXT")
                pdf.set_draw_color(30, 58, 138)
                pdf.set_line_width(0.8)
                pdf.line(LM, pdf.get_y(), RM, pdf.get_y())
                pdf.set_line_width(0.2)
                pdf.ln(4)

            # H2
            elif stripped.startswith("## ") and not stripped.startswith("### "):
                title = clean_md(stripped[3:])
                pdf.ln(4)
                y0 = pdf.get_y()
                pdf.set_fill_color(239, 246, 255)
                pdf.set_draw_color(147, 197, 253)
                pdf.rect(LM, y0, W, 9, style="FD")
                pdf.set_font("MalgunB", size=11)
                pdf.set_text_color(30, 64, 175)
                pdf.set_xy(LM + 4, y0)
                pdf.multi_cell(W - 4, 9, title, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            # H3
            elif stripped.startswith("### "):
                title = clean_md(stripped[4:])
                pdf.ln(3)
                pdf.set_draw_color(147, 197, 253)
                pdf.set_line_width(1.5)
                pdf.line(LM, pdf.get_y() + 3, LM + 4, pdf.get_y() + 3)
                pdf.set_line_width(0.2)
                pdf.set_font("MalgunB", size=10)
                pdf.set_text_color(37, 99, 235)
                pdf.set_x(LM + 6)
                pdf.multi_cell(W - 6, 6, title, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)

            # 구분선
            elif re.match(r'^[-*]{3,}$', stripped):
                pdf.ln(2)
                pdf.set_draw_color(203, 213, 225)
                pdf.line(LM, pdf.get_y(), RM, pdf.get_y())
                pdf.ln(2)

            # 번호 리스트
            elif re.match(r'^\d+\.\s', stripped):
                m = re.match(r'^(\d+)\.\s+(.*)', stripped)
                if m:
                    num, content = m.group(1), m.group(2)
                    indent_x = LM + 7
                    pdf.set_font("MalgunB", size=9.5)
                    pdf.set_text_color(30, 58, 138)
                    pdf.set_x(LM)
                    pdf.cell(7, 5.8, f"{num}.", new_x="RIGHT", new_y="TOP")
                    render_text(content, 9.5, (51, 65, 85),
                                x=indent_x, w=RM - indent_x)

            # 불릿 리스트 (들여쓰기)
            elif stripped.startswith("- ") or stripped.startswith("* "):
                content = stripped[2:].strip()
                indent = len(line) - len(line.lstrip())
                if indent >= 4:
                    dot_x, text_x = LM + 11, LM + 17
                    pdf.set_font("Malgun", size=8.5)
                    pdf.set_text_color(71, 85, 105)
                    pdf.set_x(dot_x)
                    pdf.cell(6, 5.2, "◦", new_x="RIGHT", new_y="TOP")
                    render_text(content, 8.5, (71, 85, 105),
                                x=text_x, w=RM - text_x)
                else:
                    dot_x, text_x = LM, LM + 6
                    pdf.set_font("MalgunB", size=9.5)
                    pdf.set_text_color(30, 58, 138)
                    pdf.set_x(dot_x)
                    pdf.cell(6, 5.8, "•", new_x="RIGHT", new_y="TOP")
                    render_text(content, 9.5, (51, 65, 85),
                                x=text_x, w=RM - text_x)

            # 굵은 단독 줄
            elif stripped.startswith("**") and stripped.endswith("**"):
                pdf.ln(1)
                pdf.set_font("MalgunB", size=9.5)
                pdf.set_text_color(15, 23, 42)
                pdf.set_x(LM)
                pdf.multi_cell(W, 5.8, clean_md(stripped), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(0.5)

            # 일반 본문
            else:
                render_text(stripped, 9.5, (51, 65, 85))

        except Exception:
            # 렌더링 실패 시 plain text 폴백
            try:
                fallback = clean_md(stripped)
                if fallback:
                    pdf.set_font("Malgun", size=9.5)
                    pdf.set_text_color(51, 65, 85)
                    pdf.set_x(LM)
                    pdf.multi_cell(W, 5.5, fallback, new_x="LMARGIN", new_y="NEXT")
            except Exception:
                pass

    pdf.output(output_path)
    return output_path


def generate_pdf_for_briefing(filename: str) -> dict:
    """기존 브리핑 JSON에서 PDF를 생성(또는 재생성)한다."""
    safe = os.path.basename(filename)
    if not safe.startswith("briefing_") or not safe.endswith(".json"):
        return {"success": False, "error": "잘못된 파일명"}

    json_path = os.path.join(BRIEFING_DIR, safe)
    if not os.path.exists(json_path):
        return {"success": False, "error": "브리핑 파일 없음"}

    with open(json_path, "r", encoding="utf-8") as f:
        briefing = json.load(f)

    text = briefing.get("briefing_text", "")
    if not text:
        return {"success": False, "error": "브리핑 텍스트 없음"}

    # ts 추출: briefing_20250322_1400.json → 20250322_1400
    ts = safe.replace("briefing_", "").replace(".json", "")
    pdf_name = f"briefing_{ts}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_name)
    os.makedirs(PDF_DIR, exist_ok=True)

    try:
        generate_pdf(text, pdf_path, ts)
    except Exception as e:
        return {"success": False, "error": str(e)}

    # JSON에 pdf_file 기록
    briefing["pdf_file"] = pdf_name
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)

    return {"success": True, "pdf_file": pdf_name}


def index_all_briefings() -> dict:
    """output 디렉토리의 모든 브리핑 JSON을 벡터 DB에 인덱싱한다."""
    import vector_store

    if not os.path.exists(BRIEFING_DIR):
        return {"success": False, "error": "브리핑 디렉토리 없음"}

    files = sorted([
        f for f in os.listdir(BRIEFING_DIR)
        if f.startswith("briefing_") and f.endswith(".json")
    ])

    total = len(files)
    indexed = 0
    skipped = 0
    errors = []

    for fname in files:
        path = os.path.join(BRIEFING_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                briefing = json.load(f)
            text = briefing.get("briefing_text", "")
            if not text:
                skipped += 1
                continue
            ts = fname.replace("briefing_", "").replace(".json", "")
            result = vector_store.index_intel_briefing(text, ts)
            if result.get("indexed", 0) > 0:
                indexed += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"{fname}: {e}")

    return {
        "success": True,
        "total": total,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
    }


def get_pdf_path(pdf_name: str) -> str:
    safe = os.path.basename(pdf_name)
    if not safe.startswith("briefing_") or not safe.endswith(".pdf"):
        return None
    path = os.path.join(PDF_DIR, safe)
    return path if os.path.exists(path) else None


# ─── Telegram ─────────────────────────────────────────────────────────

def _escape_md(text: str) -> str:
    for c in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-',
              '=', '|', '{', '}', '.', '!']:
        text = text.replace(c, f'\\{c}')
    return text


def _send_telegram(briefing_text: str, stats: dict, pdf_file: str = None):
    try:
        import notifier

        summary = ""
        for marker in ["요점정리", "Executive Summary"]:
            if marker in briefing_text:
                raw = briefing_text.split(marker)[-1].strip()
                if "\n##" in raw:
                    raw = raw.split("\n##")[0].strip()
                lines = [l for l in raw.splitlines() if not l.strip().startswith("#")]
                summary = "\n".join(lines).strip()
                if len(summary) > 1200:
                    summary = summary[:1200] + "..."
                break

        now = datetime.now().strftime("%Y\\-%m\\-%d %H:%M")
        msg = (
            f"🛰 *KSPD OSINT 인텔 브리핑*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 {now}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✈️ 군용기: *{stats.get('aviation_mil', 0)}*대\n"
            f"⚓ 군함: *{stats.get('maritime_naval', 0)}*척\n"
            f"💥 분쟁: *{stats.get('conflicts_events', 0)}*건\n"
            f"🔥 열점: *{stats.get('thermal_hotspots', 0)}*건\n"
            f"⚠️ 알림: *{stats.get('alerts', 0)}*건\n"
        )
        if summary:
            msg += f"━━━━━━━━━━━━━━━\n📋 *요점정리*\n{_escape_md(summary)}"

        # PDF 미리보기 페이지 링크 추가
        if pdf_file:
            cfg = get_schedule()
            base = cfg.get("public_url", "").rstrip("/")
            if base:
                pdf_url = f"{base}/intel/pdf/preview/{pdf_file}"
                # MarkdownV2 링크 URL 안에서는 ) 와 \ 만 이스케이프
                safe_url = pdf_url.replace("\\", "\\\\").replace(")", "\\)")
                msg += f"\n━━━━━━━━━━━━━━━\n[📄 PDF 미리보기]({safe_url})"

        notifier._broadcast(msg, "success")
        print("[Intel] 텔레그램 발송 완료")
    except Exception as e:
        print(f"[Intel] 텔레그램 발송 오류: {e}")


# ─── Schedule ─────────────────────────────────────────────────────────

def get_schedule() -> dict:
    if os.path.exists(SCHEDULE_PATH):
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "times": ["06:00"], "modules": [], "send_telegram": True, "save_pdf": True, "public_url": ""}


def set_schedule(config: dict) -> dict:
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    _apply_schedule(config)
    return config


def _scheduled_run():
    cfg = get_schedule()
    start_collection(cfg.get("modules", []))


def _apply_schedule(config: dict):
    try:
        from scheduler import get_scheduler
        from apscheduler.triggers.cron import CronTrigger

        sched = get_scheduler()

        # 기존 인텔 스케줄 제거
        for job in sched.get_jobs():
            if job.id.startswith("intel_sched_"):
                sched.remove_job(job.id)

        if not config.get("enabled"):
            print("[Intel] 스케줄 비활성화")
            return

        times = config.get("times", ["06:00"])
        for i, t in enumerate(times):
            try:
                h, m = t.split(":")
                sched.add_job(
                    _scheduled_run,
                    trigger=CronTrigger(hour=int(h), minute=int(m), timezone="Asia/Seoul"),
                    id=f"intel_sched_{i}",
                    replace_existing=True,
                    max_instances=1,
                )
                print(f"[Intel] 스케줄 등록: {t} KST")
            except Exception as e:
                print(f"[Intel] 스케줄 등록 실패 ({t}): {e}")
    except Exception as e:
        print(f"[Intel] 스케줄 설정 오류: {e}")


SETTINGS_PATH = os.path.join(KSPD_PATH, "config", "settings.py")

def get_osint_settings() -> dict:
    """settings.py에서 설정값을 읽어 JSON 직렬화 가능한 dict로 반환"""
    _ensure_kspd_path()
    try:
        import importlib
        import config.settings as s
        importlib.reload(s)
        return {
            "api_keys": {
                "aisstream":      s.AISSTREAM_API_KEY,
                "opensky_id":     s.OPENSKY_CLIENT_ID,
                "opensky_secret": s.OPENSKY_CLIENT_SECRET,
                "acled_email":    s.ACLED_EMAIL,
                "acled_password": s.ACLED_PASSWORD,
                "gemini":         s.GEMINI_API_KEY,
                "firms":          s.FIRMS_MAP_KEY,
                "oil_price":      s.OIL_PRICE_API_KEY,
                "commodity":      s.COMMODITY_API_KEY,
                "metals":         s.METALS_API_KEY,
                "exchange_rate":  s.EXCHANGE_RATE_API_KEY,
            },
            "watch_regions": {
                k: {"name": v["name"], "nameEn": v.get("nameEn",""),
                    "bbox": v["bbox"], "theater": v.get("theater",""),
                    "priority": v.get("priority","MEDIUM")}
                for k, v in s.WATCH_REGIONS.items()
            },
            "commodity_watchlist": {k: dict(v) for k, v in s.COMMODITY_WATCHLIST.items()},
            "commodity_alerts":    dict(s.COMMODITY_ALERT_THRESHOLDS),
            "forex_watchlist":     {k: dict(v) for k, v in s.FOREX_WATCHLIST.items()},
            "forex_alerts":        dict(s.FOREX_ALERT_THRESHOLDS),
            "watch_countries":     {k: list(v) for k, v in s.WATCH_COUNTRIES.items()},
            "military_facilities": list(s.MILITARY_FACILITIES),
            "known_naval_mmsi":    dict(s.KNOWN_NAVAL_MMSI),
            "military_callsigns":  [p.pattern for p in s.MILITARY_CALLSIGN_PATTERNS],
        }
    except Exception as e:
        return {"error": str(e)}


def save_osint_settings(data: dict) -> dict:
    """설정값을 settings.py에 덮어씀"""
    _ensure_kspd_path()
    try:
        # 현재 파일 읽기
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        def replace_str(content, key, val):
            import re
            return re.sub(
                rf'^({key}\s*=\s*)["\'][^"\']*["\']',
                lambda m: m.group(1) + '"' + val.replace('\\','\\\\').replace('"','\\"') + '"',
                content, flags=re.MULTILINE
            )

        keys = data.get("api_keys", {})
        mapping = {
            "AISSTREAM_API_KEY":     keys.get("aisstream"),
            "OPENSKY_CLIENT_ID":     keys.get("opensky_id"),
            "OPENSKY_CLIENT_SECRET": keys.get("opensky_secret"),
            "ACLED_EMAIL":           keys.get("acled_email"),
            "ACLED_PASSWORD":        keys.get("acled_password"),
            "GEMINI_API_KEY":        keys.get("gemini"),
            "FIRMS_MAP_KEY":         keys.get("firms"),
            "OIL_PRICE_API_KEY":     keys.get("oil_price"),
            "COMMODITY_API_KEY":     keys.get("commodity"),
            "METALS_API_KEY":        keys.get("metals"),
            "EXCHANGE_RATE_API_KEY": keys.get("exchange_rate"),
        }
        for k, v in mapping.items():
            if v is not None:
                content = replace_str(content, k, v)

        # WATCH_REGIONS 교체
        if "watch_regions" in data:
            import json as _json, re
            regions = data["watch_regions"]
            lines = ["WATCH_REGIONS = {"]
            for rid, rv in regions.items():
                lines.append(f'    "{rid}": {{')
                lines.append(f'        "name": "{rv["name"]}", "nameEn": "{rv.get("nameEn","")}",')
                lines.append(f'        "bbox": {rv["bbox"]},')
                lines.append(f'        "theater": "{rv.get("theater","")}", "priority": "{rv.get("priority","MEDIUM")}"')
                lines.append("    },")
            lines.append("}")
            new_block = "\n".join(lines)
            content = re.sub(
                r'WATCH_REGIONS\s*=\s*\{.*?\n\}',
                new_block, content, flags=re.DOTALL
            )

        # WATCH_COUNTRIES 교체
        if "watch_countries" in data:
            import re
            wc = data["watch_countries"]
            lines = ["WATCH_COUNTRIES = {"]
            for theater, countries in wc.items():
                c_str = ", ".join(f'"{c}"' for c in countries)
                lines.append(f'    "{theater}": [{c_str}],')
            lines.append("}")
            new_block = "\n".join(lines)
            content = re.sub(
                r'WATCH_COUNTRIES\s*=\s*\{.*?\n\}',
                new_block, content, flags=re.DOTALL
            )

        # MILITARY_FACILITIES 교체
        if "military_facilities" in data:
            import re
            facs = data["military_facilities"]
            lines = ["MILITARY_FACILITIES = ["]
            for f in facs:
                lines.append(f'    {{"name": "{f["name"]}", "lat": {f["lat"]}, "lon": {f["lon"]}, "radius_km": {f["radius_km"]}}},')
            lines.append("]")
            new_block = "\n".join(lines)
            content = re.sub(
                r'MILITARY_FACILITIES\s*=\s*\[.*?\n\]',
                new_block, content, flags=re.DOTALL
            )

        # KNOWN_NAVAL_MMSI 교체
        if "known_naval_mmsi" in data:
            import re
            mmsi = data["known_naval_mmsi"]
            lines = ["KNOWN_NAVAL_MMSI = {"]
            for k, v in mmsi.items():
                lines.append(f'    "{k}": {{"name": "{v["name"]}", "type": "{v["type"]}", "nation": "{v["nation"]}"}},')
            lines.append("}")
            new_block = "\n".join(lines)
            content = re.sub(
                r'KNOWN_NAVAL_MMSI\s*=\s*\{.*?\n\}',
                new_block, content, flags=re.DOTALL
            )

        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        # 모듈 캐시 무효화
        import sys
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("config"):
                del sys.modules[mod_name]

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def init_intel_schedule():
    cfg = get_schedule()
    if cfg.get("enabled"):
        _apply_schedule(cfg)


# ─── Briefings ────────────────────────────────────────────────────────

def list_briefings() -> list:
    if not os.path.exists(BRIEFING_DIR):
        return []
    result = []
    for fname in sorted(os.listdir(BRIEFING_DIR), reverse=True):
        if fname.startswith("briefing_") and fname.endswith(".json"):
            fpath = os.path.join(BRIEFING_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                pdf_name = fname.replace(".json", ".pdf")
                result.append({
                    "filename": fname,
                    "generated_at": meta.get("generated_at", ""),
                    "generated_by": meta.get("generated_by", ""),
                    "icd203": meta.get("icd203", False),
                    "has_pdf": os.path.exists(os.path.join(PDF_DIR, pdf_name)),
                    "pdf_file": pdf_name,
                })
            except Exception:
                pass
    return result[:50]


def get_briefing(filename: str) -> dict:
    safe_name = os.path.basename(filename)
    if not safe_name.startswith("briefing_"):
        return None
    fpath = os.path.join(BRIEFING_DIR, safe_name)
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    pdf_name = safe_name.replace(".json", ".pdf")
    data["has_pdf"] = os.path.exists(os.path.join(PDF_DIR, pdf_name))
    data["pdf_file"] = pdf_name
    return data


def get_latest_status() -> dict:
    path = os.path.join(BRIEFING_DIR, "latest_status.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
