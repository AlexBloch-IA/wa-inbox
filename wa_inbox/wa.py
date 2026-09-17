"""Read-only access to the local wacli mirror.

This module deliberately contains no WhatsApp write command: no send, no
chats mark-read, no presence. That is what keeps your chats unread.
"""
import json
import os
import subprocess

ENV = dict(os.environ, WACLI_READONLY="1")
WACLI = os.environ.get("WACLI_BIN", "wacli")


def configure(wacli_bin) -> None:
    global WACLI
    WACLI = wacli_bin


def _wacli(args, timeout=60) -> str:
    r = subprocess.run([WACLI, "--read-only", *args], capture_output=True, text=True, env=ENV, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"wacli {' '.join(args)} failed: {r.stderr.strip()[:500]}")
    return r.stdout


def _data(raw_json: str):
    """wacli --json wraps everything in {"success", "data", "error"}; return data (or a bare object)."""
    out = json.loads(raw_json)
    if isinstance(out, dict) and "success" in out and "data" in out:
        if not out["success"]:
            raise RuntimeError(f"wacli error: {out.get('error')}")
        return out["data"]
    return out


def is_authenticated() -> bool:
    try:
        return bool(_data(_wacli(["auth", "status", "--json"])).get("authenticated"))
    except (RuntimeError, json.JSONDecodeError):
        return False


def _norm(raw) -> dict:
    return {
        "id": raw["MsgID"], "chat_jid": raw["ChatJID"], "chat_name": raw.get("ChatName") or raw["ChatJID"],
        "is_group": raw["ChatJID"].endswith("@g.us"),
        "sender_jid": raw.get("SenderJID", ""), "sender_name": raw.get("SenderName") or raw.get("SenderJID", ""),
        "ts": raw["Timestamp"], "text": raw.get("Text") or "", "media_type": raw.get("MediaType") or "",
        "local_path": raw.get("LocalPath") or "", "mime_type": raw.get("MimeType") or "",
        "caption": raw.get("MediaCaption") or "", "context": [],
    }


KEPT_MEDIA = ("audio", "image")


def keepable(m) -> bool:
    """Worth showing the classifier: not a broadcast, and carrying text, voice or a photo."""
    if m["chat_jid"].endswith("@newsletter") or m["chat_jid"].startswith("status@"):
        return False
    if m["media_type"] in KEPT_MEDIA:
        return True
    return bool(m["text"].strip())


def list_new(after_rfc3339, limit=500) -> list:
    """Every message received since `after`, normalised, unfiltered.

    Filtering is the caller's job: the runner needs to see the rows it discards
    so it can still advance its cursor past a window made only of stickers.
    """
    args = ["messages", "list", "--json", "--from-them", "--asc", "--limit", str(limit)]
    if after_rfc3339:
        args += ["--after", after_rfc3339]
    data = _data(_wacli(args))
    raw = data.get("messages", []) if isinstance(data, dict) else data
    return [_norm(r) for r in raw if not r.get("FromMe")]


def _who(r) -> str:
    if r.get("FromMe"):
        return "me"
    return r.get("SenderName") or r.get("SenderJID") or "?"


def group_context(chat_jid, msg_id, n=3) -> list:
    out = _data(_wacli(["messages", "context", "--json", "--chat", chat_jid, "--id", msg_id,
                        "--before", str(n), "--after", "0"]))
    msgs = out if isinstance(out, list) else out.get("messages", [])
    return [f"{_who(r)}: {r.get('Text', '')}" for r in msgs
            if r.get("MsgID") != msg_id and (r.get("Text") or "").strip()]


def download_media(chat_jid, msg_id, out_path) -> str:
    _wacli(["media", "download", "--chat", chat_jid, "--id", msg_id, "--output", out_path], timeout=120)
    return out_path
