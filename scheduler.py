"""News collection scheduler using APScheduler."""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from news_collector import collect_all, get_available_sources
import vector_store
import notifier
import intel_runner

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scheduler_config.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "scheduler_log.json")

_scheduler = None
_log_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
        _scheduler.start()
    return _scheduler


def _load_config() -> list[dict]:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_config(pipelines: list[dict]):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(pipelines, f, ensure_ascii=False, indent=2)


def _load_logs() -> list[dict]:
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data[-200:]  # Keep last 200
    return []


def _append_log(entry: dict):
    with _log_lock:
        logs = _load_logs()
        logs.append(entry)
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(logs[-200:], f, ensure_ascii=False, indent=2)


def _run_pipeline(pipeline_id: str):
    """Execute a pipeline's collection task."""
    pipelines = _load_config()
    pipeline = next((p for p in pipelines if p["id"] == pipeline_id), None)
    if not pipeline or not pipeline.get("enabled", True):
        return

    log_entry = {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline["name"],
        "started_at": datetime.now().isoformat(),
        "status": "running",
    }

    try:
        sources = pipeline.get("sources") or None
        categories = pipeline.get("categories") or None
        max_per_feed = pipeline.get("max_per_feed", 10)
        fetch_body = pipeline.get("fetch_body", True)
        include_intel = pipeline.get("include_intel", False)
        intel_modules = pipeline.get("intel_modules") or []

        articles = collect_all(
            sources=sources, categories=categories,
            fetch_body=fetch_body, max_per_feed=max_per_feed,
        )

        result = vector_store.index_articles(articles)

        # 인텔리전스 수집
        if include_intel:
            intel_job_id = intel_runner.start_collection(modules=intel_modules if intel_modules else None)
            result["intel_job_id"] = intel_job_id
            result["intel_started"] = True

        log_entry["status"] = "success"
        log_entry["finished_at"] = datetime.now().isoformat()
        log_entry["result"] = result

        # Update pipeline last_run
        for p in pipelines:
            if p["id"] == pipeline_id:
                p["last_run"] = datetime.now().isoformat()
                p["last_status"] = "success"
                p["last_result"] = result
        _save_config(pipelines)

        # Telegram notification
        notifier.notify_collection_result(pipeline["name"], result)

    except Exception as e:
        log_entry["status"] = "error"
        log_entry["finished_at"] = datetime.now().isoformat()
        log_entry["error"] = str(e)

        for p in pipelines:
            if p["id"] == pipeline_id:
                p["last_run"] = datetime.now().isoformat()
                p["last_status"] = "error"
                p["last_error"] = str(e)
        _save_config(pipelines)

        # Telegram error notification
        notifier.notify_collection_error(pipeline["name"], str(e))

    _append_log(log_entry)


def create_pipeline(config: dict) -> dict:
    """Create a new collection pipeline."""
    pipelines = _load_config()

    pipeline = {
        "id": f"pipe_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(pipelines)}",
        "name": config.get("name", "새 파이프라인"),
        "enabled": config.get("enabled", True),
        "sources": config.get("sources", []),
        "categories": config.get("categories", []),
        "max_per_feed": config.get("max_per_feed", 10),
        "fetch_body": config.get("fetch_body", True),
        "schedule_type": config.get("schedule_type", "interval"),  # interval or cron
        "interval_minutes": config.get("interval_minutes", 60),
        "cron_expression": config.get("cron_expression", "0 */1 * * *"),
        "include_intel": config.get("include_intel", False),
        "intel_modules": config.get("intel_modules", []),
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "last_status": None,
        "last_result": None,
    }

    pipelines.append(pipeline)
    _save_config(pipelines)

    if pipeline["enabled"]:
        _schedule_pipeline(pipeline)

    return pipeline


def update_pipeline(pipeline_id: str, config: dict) -> dict:
    """Update an existing pipeline."""
    pipelines = _load_config()
    scheduler = get_scheduler()

    for i, p in enumerate(pipelines):
        if p["id"] == pipeline_id:
            # Remove old job
            try:
                scheduler.remove_job(pipeline_id)
            except Exception:
                pass

            p.update({
                "name": config.get("name", p["name"]),
                "enabled": config.get("enabled", p["enabled"]),
                "sources": config.get("sources", p["sources"]),
                "categories": config.get("categories", p["categories"]),
                "max_per_feed": config.get("max_per_feed", p["max_per_feed"]),
                "fetch_body": config.get("fetch_body", p["fetch_body"]),
                "schedule_type": config.get("schedule_type", p["schedule_type"]),
                "interval_minutes": config.get("interval_minutes", p["interval_minutes"]),
                "cron_expression": config.get("cron_expression", p["cron_expression"]),
                "include_intel": config.get("include_intel", p.get("include_intel", False)),
                "intel_modules": config.get("intel_modules", p.get("intel_modules", [])),
            })

            _save_config(pipelines)

            if p["enabled"]:
                _schedule_pipeline(p)

            return p

    return {"error": "파이프라인을 찾을 수 없습니다."}


def delete_pipeline(pipeline_id: str) -> dict:
    pipelines = _load_config()
    scheduler = get_scheduler()

    try:
        scheduler.remove_job(pipeline_id)
    except Exception:
        pass

    pipelines = [p for p in pipelines if p["id"] != pipeline_id]
    _save_config(pipelines)
    return {"success": True}


def toggle_pipeline(pipeline_id: str) -> dict:
    pipelines = _load_config()
    scheduler = get_scheduler()

    for p in pipelines:
        if p["id"] == pipeline_id:
            p["enabled"] = not p["enabled"]
            _save_config(pipelines)

            if p["enabled"]:
                _schedule_pipeline(p)
            else:
                try:
                    scheduler.remove_job(pipeline_id)
                except Exception:
                    pass

            return p

    return {"error": "not found"}


def run_pipeline_now(pipeline_id: str) -> dict:
    """Manually trigger a pipeline."""
    thread = threading.Thread(target=_run_pipeline, args=(pipeline_id,), daemon=True)
    thread.start()
    return {"success": True, "message": "파이프라인이 실행되었습니다."}


def _schedule_pipeline(pipeline: dict):
    scheduler = get_scheduler()

    try:
        scheduler.remove_job(pipeline["id"])
    except Exception:
        pass

    if pipeline.get("schedule_type") == "cron":
        parts = pipeline.get("cron_expression", "0 */1 * * *").split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else "0",
            hour=parts[1] if len(parts) > 1 else "*",
            day=parts[2] if len(parts) > 2 else "*",
            month=parts[3] if len(parts) > 3 else "*",
            day_of_week=parts[4] if len(parts) > 4 else "*",
        )
    else:
        trigger = IntervalTrigger(minutes=pipeline.get("interval_minutes", 60))

    scheduler.add_job(
        _run_pipeline,
        trigger=trigger,
        id=pipeline["id"],
        args=[pipeline["id"]],
        replace_existing=True,
        max_instances=1,
    )


def get_pipelines() -> list[dict]:
    """Get all pipelines with their next run time."""
    pipelines = _load_config()
    scheduler = get_scheduler()

    for p in pipelines:
        job = scheduler.get_job(p["id"])
        if job:
            p["next_run"] = job.next_run_time.isoformat() if job.next_run_time else None
            p["is_scheduled"] = True
        else:
            p["next_run"] = None
            p["is_scheduled"] = False

    return pipelines


def get_logs(limit: int = 50) -> list[dict]:
    logs = _load_logs()
    return list(reversed(logs[-limit:]))


def init_scheduler():
    """Load saved pipelines and schedule them on startup."""
    pipelines = _load_config()
    for p in pipelines:
        if p.get("enabled", True):
            _schedule_pipeline(p)
