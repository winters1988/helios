"""Telegram notification module - supports multiple channels."""

import os
import json
import asyncio
from datetime import datetime

import telegram

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "telegram_config.json")


def _load_channels() -> list[dict]:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Migration: old single-channel format → list
            if isinstance(data, dict) and "bot_token" in data:
                ch = {
                    "id": "ch_migrated",
                    "name": "기본 채널",
                    "bot_token": data.get("bot_token", ""),
                    "chat_id": data.get("chat_id", ""),
                    "enabled": data.get("enabled", False),
                    "notify_on_success": data.get("notify_on_success", True),
                    "notify_on_error": data.get("notify_on_error", True),
                }
                _save_channels([ch])
                return [ch]
            return data if isinstance(data, list) else []
    return []


def _save_channels(channels: list[dict]):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


def get_channels() -> list[dict]:
    channels = _load_channels()
    safe = []
    for ch in channels:
        c = dict(ch)
        t = c.get("bot_token", "")
        c["bot_token_masked"] = (t[:8] + "..." + t[-4:]) if len(t) > 12 else ("***" if t else "")
        safe.append(c)
    return safe


def add_channel(config: dict) -> dict:
    channels = _load_channels()
    ch = {
        "id": f"ch_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(channels)}",
        "name": config.get("name", "새 채널"),
        "bot_token": config.get("bot_token", ""),
        "chat_id": config.get("chat_id", ""),
        "enabled": config.get("enabled", True),
        "notify_on_success": config.get("notify_on_success", True),
        "notify_on_error": config.get("notify_on_error", True),
    }
    channels.append(ch)
    _save_channels(channels)
    return {"success": True, "channel": ch}


def update_channel(channel_id: str, config: dict) -> dict:
    channels = _load_channels()
    for ch in channels:
        if ch["id"] == channel_id:
            ch["name"] = config.get("name", ch["name"])
            ch["bot_token"] = config.get("bot_token", ch["bot_token"])
            ch["chat_id"] = config.get("chat_id", ch["chat_id"])
            ch["enabled"] = config.get("enabled", ch["enabled"])
            ch["notify_on_success"] = config.get("notify_on_success", ch["notify_on_success"])
            ch["notify_on_error"] = config.get("notify_on_error", ch["notify_on_error"])
            _save_channels(channels)
            return {"success": True, "channel": ch}
    return {"success": False, "error": "채널을 찾을 수 없습니다."}


def delete_channel(channel_id: str) -> dict:
    channels = _load_channels()
    channels = [ch for ch in channels if ch["id"] != channel_id]
    _save_channels(channels)
    return {"success": True}


def toggle_channel(channel_id: str) -> dict:
    channels = _load_channels()
    for ch in channels:
        if ch["id"] == channel_id:
            ch["enabled"] = not ch["enabled"]
            _save_channels(channels)
            return {"success": True, "channel": ch}
    return {"success": False, "error": "채널을 찾을 수 없습니다."}


# ─── Message formatting ──────────────────────────────────────────────

def _escape_md(text: str) -> str:
    for c in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(c, f'\\{c}')
    return text


def _format_success_message(pipeline_name: str, result: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"✅ *뉴스 수집 완료*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 파이프라인: *{_escape_md(pipeline_name)}*\n"
        f"🕐 시간: {_escape_md(now)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📰 수집 기사: *{result.get('total_articles', 0)}*건\n"
        f"📥 신규 색인: *{result.get('indexed', 0)}*건\n"
        f"⏭ 건너뜀: {result.get('skipped', 0)}건\n"
        f"🧩 생성 청크: *{result.get('total_chunks', 0)}*개\n"
    )


def _format_error_message(pipeline_name: str, error: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"❌ *뉴스 수집 오류*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 파이프라인: *{_escape_md(pipeline_name)}*\n"
        f"🕐 시간: {_escape_md(now)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚠️ 오류: {_escape_md(error)}\n"
    )


# ─── Sending ─────────────────────────────────────────────────────────

async def _send_async(bot_token: str, chat_id: str, message: str):
    bot = telegram.Bot(token=bot_token)
    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


def _send_to_channel(ch: dict, message: str) -> dict:
    """Send message to a single channel."""
    try:
        asyncio.run(_send_async(ch["bot_token"], ch["chat_id"], message))
        return {"success": True, "channel": ch["name"]}
    except Exception as e:
        return {"success": False, "channel": ch["name"], "error": str(e)}


def _broadcast(message: str, event_type: str = "success"):
    """Send message to all enabled channels matching event_type."""
    channels = _load_channels()
    results = []
    for ch in channels:
        if not ch.get("enabled"):
            continue
        if event_type == "success" and not ch.get("notify_on_success", True):
            continue
        if event_type == "error" and not ch.get("notify_on_error", True):
            continue
        results.append(_send_to_channel(ch, message))
    return results


def notify_collection_result(pipeline_name: str, result: dict):
    msg = _format_success_message(pipeline_name, result)
    _broadcast(msg, "success")


def notify_collection_error(pipeline_name: str, error: str):
    msg = _format_error_message(pipeline_name, error)
    _broadcast(msg, "error")


def test_channel(channel_id: str) -> dict:
    """Send test message to a specific channel."""
    channels = _load_channels()
    ch = next((c for c in channels if c["id"] == channel_id), None)
    if not ch:
        return {"success": False, "error": "채널을 찾을 수 없습니다."}
    if not ch.get("bot_token") or not ch.get("chat_id"):
        return {"success": False, "error": "Bot Token과 Chat ID를 설정하세요."}

    test_msg = (
        "🔔 *OSINT Recon 테스트*\n"
        "━━━━━━━━━━━━━━━\n"
        f"📡 채널: *{_escape_md(ch['name'])}*\n"
        "텔레그램 연결이 정상입니다\\!\n"
        "수집 알림이 이 채팅으로 전송됩니다\\.\n"
    )
    return _send_to_channel(ch, test_msg)
