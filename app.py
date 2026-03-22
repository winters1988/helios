"""OSINT News Collection & Vector Search Platform"""

import os
import json
import hashlib
import secrets
import threading
from flask import Flask, render_template, request, jsonify, redirect, session

from news_collector import (
    collect_all, collect_from_url, get_available_sources,
    RSS_SOURCES, Article
)
import vector_store
import scheduler

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

_jobs = {}
_job_lock = threading.Lock()

# Password hash (SHA-256) — never store plaintext
_PASSWORD_HASH = hashlib.sha256("0857".encode()).hexdigest()


# ─── Auth ──────────────────────────────────────────────────────────────

@app.before_request
def require_login():
    """All routes require login except /login and static files."""
    allowed = ("/login", "/static/", "/api/intel/pdf/view/", "/api/intel/pdf/", "/intel/pdf/preview/")
    if any(request.path.startswith(p) for p in allowed):
        return
    if not session.get("authenticated"):
        if request.is_json or request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "인증이 필요합니다."}), 401
        return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if hashlib.sha256(pw.encode()).hexdigest() == _PASSWORD_HASH:
            session["authenticated"] = True
            session.permanent = True
            return redirect("/")
        error = "비밀번호가 올바르지 않습니다."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ─── Pages ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    sources = get_available_sources()
    return render_template("dashboard.html", sources=sources)


@app.route("/browse")
def browse_page():
    return render_template("browse.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


# ─── News Sources API ─────────────────────────────────────────────────

@app.route("/api/sources")
def api_sources():
    """Get all configured RSS sources."""
    return jsonify({"success": True, "sources": get_available_sources()})


@app.route("/api/sources/detail")
def api_sources_detail():
    """Get full RSS source config with URLs."""
    result = {}
    for name, feeds in RSS_SOURCES.items():
        result[name] = {cat: url for cat, url in feeds.items()}
    return jsonify({"success": True, "sources": result})


@app.route("/api/sources/add", methods=["POST"])
def api_add_source():
    """Add a custom RSS source."""
    data = request.get_json()
    name = data.get("name", "").strip()
    feeds = data.get("feeds", {})  # {"카테고리": "rss_url", ...}

    if not name or not feeds:
        return jsonify({"success": False, "error": "소스 이름과 피드 URL이 필요합니다."})

    # Add to RSS_SOURCES at runtime + save to config
    RSS_SOURCES[name] = feeds
    _save_custom_sources()
    return jsonify({"success": True, "message": f"'{name}' 소스가 추가되었습니다."})


@app.route("/api/sources/remove", methods=["POST"])
def api_remove_source():
    """Remove a custom RSS source."""
    data = request.get_json()
    name = data.get("name", "").strip()
    if name in RSS_SOURCES:
        del RSS_SOURCES[name]
        _save_custom_sources()
        return jsonify({"success": True, "message": f"'{name}' 소스가 삭제되었습니다."})
    return jsonify({"success": False, "error": "소스를 찾을 수 없습니다."})


def _load_custom_sources():
    """Load custom sources from config file."""
    import os
    path = os.path.join(os.path.dirname(__file__), "custom_sources.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            custom = json.load(f)
            RSS_SOURCES.update(custom)


def _save_custom_sources():
    """Save current custom sources (non-default) to file."""
    import os
    from news_collector import RSS_SOURCES as default_check
    path = os.path.join(os.path.dirname(__file__), "custom_sources.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(RSS_SOURCES), f, ensure_ascii=False, indent=2)


# ─── News Collection API ──────────────────────────────────────────────

@app.route("/api/news/collect", methods=["POST"])
def api_news_collect():
    data = request.get_json()
    sources = data.get("sources")
    categories = data.get("categories")
    max_per_feed = data.get("max_per_feed", 10)
    fetch_body = data.get("fetch_body", True)

    job_id = f"job_{len(_jobs) + 1}"
    job_state = {
        "id": job_id, "status": "running", "progress": 0,
        "total": 0, "current": "", "result": None, "errors": [],
    }

    with _job_lock:
        _jobs[job_id] = job_state

    def run_collection():
        try:
            job_state["current"] = "뉴스 기사 수집 중..."
            articles = collect_all(
                sources=sources, categories=categories,
                fetch_body=fetch_body, max_per_feed=max_per_feed,
            )
            job_state["total"] = len(articles)

            if not articles:
                job_state["status"] = "done"
                job_state["result"] = {"total_articles": 0, "indexed": 0,
                                       "skipped": 0, "total_chunks": 0}
                return

            def progress_cb(current, total, action, title):
                job_state["progress"] = current
                job_state["total"] = total
                job_state["current"] = f"[{current}/{total}] {title}"

            result = vector_store.index_articles(articles, progress_callback=progress_cb)
            job_state["status"] = "done"
            job_state["result"] = result
        except Exception as e:
            job_state["status"] = "error"
            job_state["errors"].append(str(e))

    threading.Thread(target=run_collection, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "started"})


@app.route("/api/news/collect/url", methods=["POST"])
def api_news_collect_url():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "URL을 입력해주세요."})

    article = collect_from_url(url)
    if not article:
        return jsonify({"success": False, "error": "기사를 추출할 수 없습니다."})

    result = vector_store.index_articles([article])
    return jsonify({
        "success": True,
        "article": {"title": article.title, "source": article.source,
                     "content_length": len(article.content)},
        "index": result,
    })


@app.route("/api/news/job/<job_id>")
def api_job_status(job_id):
    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    return jsonify(job)


@app.route("/api/news/jobs")
def api_all_jobs():
    with _job_lock:
        return jsonify({"success": True, "jobs": list(_jobs.values())})


@app.route("/api/news/search", methods=["POST"])
def api_news_search():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"success": False, "error": "검색어를 입력해주세요."})

    try:
        results = vector_store.search(
            query=query,
            top_k=data.get("top_k", 10),
            sources=data.get("sources"),
            categories=data.get("categories"),
        )
        return jsonify({"success": True, "results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/news/stats")
def api_news_stats():
    try:
        stats = vector_store.get_stats()
        return jsonify({"success": True, **stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/news/reset", methods=["POST"])
def api_news_reset():
    try:
        return jsonify(vector_store.delete_collection())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/news/browse")
def api_news_browse():
    try:
        result = vector_store.browse_articles(
            offset=request.args.get("offset", 0, type=int),
            limit=request.args.get("limit", 50, type=int),
            source_filter=request.args.get("source", None),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/news/article/<article_id>")
def api_news_article_detail(article_id):
    try:
        return jsonify(vector_store.get_article_detail(article_id))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─── Scheduler / Pipeline API ─────────────────────────────────────────

@app.route("/api/pipelines")
def api_get_pipelines():
    return jsonify({"success": True, "pipelines": scheduler.get_pipelines()})


@app.route("/api/pipelines", methods=["POST"])
def api_create_pipeline():
    data = request.get_json()
    pipeline = scheduler.create_pipeline(data)
    return jsonify({"success": True, "pipeline": pipeline})


@app.route("/api/pipelines/<pipeline_id>", methods=["PUT"])
def api_update_pipeline(pipeline_id):
    data = request.get_json()
    result = scheduler.update_pipeline(pipeline_id, data)
    return jsonify({"success": True, "pipeline": result})


@app.route("/api/pipelines/<pipeline_id>", methods=["DELETE"])
def api_delete_pipeline(pipeline_id):
    return jsonify(scheduler.delete_pipeline(pipeline_id))


@app.route("/api/pipelines/<pipeline_id>/toggle", methods=["POST"])
def api_toggle_pipeline(pipeline_id):
    result = scheduler.toggle_pipeline(pipeline_id)
    return jsonify({"success": True, "pipeline": result})


@app.route("/api/pipelines/<pipeline_id>/run", methods=["POST"])
def api_run_pipeline(pipeline_id):
    return jsonify(scheduler.run_pipeline_now(pipeline_id))


@app.route("/api/pipelines/logs")
def api_pipeline_logs():
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"success": True, "logs": scheduler.get_logs(limit)})


# ─── Telegram API ─────────────────────────────────────────────────────

import notifier


@app.route("/api/telegram/channels")
def api_telegram_channels():
    return jsonify({"success": True, "channels": notifier.get_channels()})


@app.route("/api/telegram/channels", methods=["POST"])
def api_telegram_add_channel():
    return jsonify(notifier.add_channel(request.get_json()))


@app.route("/api/telegram/channels/<channel_id>", methods=["PUT"])
def api_telegram_update_channel(channel_id):
    return jsonify(notifier.update_channel(channel_id, request.get_json()))


@app.route("/api/telegram/channels/<channel_id>", methods=["DELETE"])
def api_telegram_delete_channel(channel_id):
    return jsonify(notifier.delete_channel(channel_id))


@app.route("/api/telegram/channels/<channel_id>/toggle", methods=["POST"])
def api_telegram_toggle_channel(channel_id):
    return jsonify(notifier.toggle_channel(channel_id))


@app.route("/api/telegram/channels/<channel_id>/test", methods=["POST"])
def api_telegram_test_channel(channel_id):
    return jsonify(notifier.test_channel(channel_id))


# ─── Intel (KSPD OSINT) API ───────────────────────────────────────────

import intel_runner


@app.route("/intel")
def intel_page():
    return render_template("intel.html")


@app.route("/api/intel/run", methods=["POST"])
def api_intel_run():
    data = request.get_json()
    modules = data.get("modules", [])
    job_id = intel_runner.start_collection(modules)
    return jsonify({"job_id": job_id, "status": "started"})


@app.route("/api/intel/job/<job_id>")
def api_intel_job(job_id):
    job = intel_runner.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.route("/api/intel/jobs")
def api_intel_jobs():
    return jsonify({"jobs": intel_runner.get_jobs()})


@app.route("/api/intel/briefings")
def api_intel_briefings():
    return jsonify({"briefings": intel_runner.list_briefings()})


@app.route("/api/intel/briefing/<filename>")
def api_intel_briefing(filename):
    data = intel_runner.get_briefing(filename)
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@app.route("/api/intel/status")
def api_intel_status():
    return jsonify(intel_runner.get_latest_status())


@app.route("/api/intel/schedule", methods=["GET"])
def api_intel_schedule_get():
    return jsonify(intel_runner.get_schedule())


@app.route("/api/intel/schedule", methods=["POST"])
def api_intel_schedule_set():
    config = request.get_json()
    return jsonify(intel_runner.set_schedule(config))


@app.route("/api/intel/index-all", methods=["POST"])
def api_intel_index_all():
    def _run():
        result = intel_runner.index_all_briefings()
        _index_jobs["latest"] = result

    _index_jobs["latest"] = {"status": "running"}
    import threading
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/intel/index-all/status")
def api_intel_index_all_status():
    return jsonify(_index_jobs.get("latest", {"status": "idle"}))


_index_jobs = {}


@app.route("/api/intel/pdf/generate", methods=["POST"])
def api_intel_pdf_generate():
    data = request.get_json()
    filename = data.get("filename", "")
    result = intel_runner.generate_pdf_for_briefing(filename)
    return jsonify(result)


@app.route("/api/intel/pdf/view/<filename>")
def api_intel_pdf_view(filename):
    from flask import send_file
    path = intel_runner.get_pdf_path(filename)
    if not path:
        return jsonify({"error": "PDF not found"}), 404
    return send_file(path, as_attachment=False, mimetype="application/pdf")


@app.route("/api/intel/pdf/<filename>")
def api_intel_pdf(filename):
    from flask import send_file
    path = intel_runner.get_pdf_path(filename)
    if not path:
        return jsonify({"error": "PDF not found"}), 404
    return send_file(path, as_attachment=True,
                     download_name=filename,
                     mimetype="application/pdf")


@app.route("/intel/pdf/preview/<filename>")
def intel_pdf_preview_page(filename):
    """공개 PDF 미리보기 HTML 페이지 (Telegram 링크용, 인증 불필요)"""
    return render_template("pdf_preview.html", filename=filename)


@app.route("/api/osint/settings")
def api_osint_settings_get():
    return jsonify(intel_runner.get_osint_settings())


@app.route("/api/osint/settings", methods=["POST"])
def api_osint_settings_save():
    data = request.get_json()
    return jsonify(intel_runner.save_osint_settings(data))


@app.route("/osint-settings")
def osint_settings_page():
    return render_template("osint_settings.html")


# ─── Chat API ─────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"success": False, "error": "메시지를 입력해주세요."})

    try:
        results = vector_store.search(query=message, top_k=5)
        stats = vector_store.get_stats()

        if not results:
            return jsonify({
                "success": True,
                "response": "관련 기사를 찾지 못했습니다. 뉴스를 먼저 수집해주세요.",
                "articles": [],
                "db_stats": stats,
            })

        response_text = f"**\"{message}\"**에 대해 {len(results)}건의 관련 기사를 찾았습니다."

        return jsonify({
            "success": True,
            "response": response_text,
            "articles": results,
            "db_stats": stats,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─── Startup ──────────────────────────────────────────────────────────

_load_custom_sources()
scheduler.init_scheduler()
intel_runner.init_intel_schedule()

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  OSINT 뉴스 수집 플랫폼")
    print("  http://localhost:5000 에서 접속하세요")
    print("=" * 50 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
