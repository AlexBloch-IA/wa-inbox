"""wa-inbox: turn incoming WhatsApp requests into Google Tasks. Nothing is ever marked read."""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

from . import classify, config, gtasks, state, transcribe, wa

OVERLAP = timedelta(minutes=5)
PHOTO_WINDOW = timedelta(minutes=5)
EXT_BY_MIME = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
               "image/webp": ".webp", "image/heic": ".heic", "image/gif": ".gif"}
AUTH_MARKERS = ("invalid_grant", "unauthorized_client", "401", "invalid_client",
                "could not be found in the keychain", "token has been expired or revoked")


def notify(title, msg):
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'], capture_output=True)


def _log(log_dir, line):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / f"{datetime.now():%Y-%m-%d}.log", "a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} | {line}\n")
    for old in sorted(log_dir.glob("????-??-??.log"))[:-30]:
        old.unlink()


def _slug(text, n=40) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text or "")[:n].strip("_") or "x"


def save_image(m, d, images_dir) -> str:
    """Download a photo into images_dir. Returns the path, or '' on failure."""
    if not images_dir:
        return ""
    os.makedirs(images_dir, exist_ok=True)
    ext = EXT_BY_MIME.get(m.get("mime_type", "").split(";")[0].strip().lower(), ".jpg")
    name = f"{m['ts'].replace('-', '').replace(':', '')[:13]}_{_slug(m['chat_name'], 30)}_{_slug(m['id'], 20)}{ext}"
    out = os.path.realpath(os.path.join(images_dir, name))
    if not out.startswith(os.path.realpath(images_dir) + os.sep):
        return ""
    try:
        return d.download_media(m["chat_jid"], m["id"], out)
    except Exception:  # noqa: BLE001
        return ""


def _ts(m):
    return datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))


def assign_photos(decisions, by_id) -> dict:
    """Decide which photos each created task carries, keyed by the task's message id.

    A task starts with the photos Claude declared: its own message and whatever it
    folded in through `grouped_message_ids`. That alone is not enough, because one
    complaint often arrives as several shots minutes apart and the model reliably
    names only some of them. So each task then picks up any still-unclaimed photo
    from the same chat inside the time span it already covers, widened by
    PHOTO_WINDOW. Tasks claim in chronological order and a photo is only ever
    claimed once, so two tasks in one chat never fight over the same image.

    The sweep only takes photos with no caption of their own. A captioned photo
    was judged on its own merits by the classifier, so overriding that verdict
    would copy unrelated private pictures into the images folder and write their
    paths into a task.
    """
    created = [d for d in decisions if d["create"] and d["message_id"] in by_id]
    created.sort(key=lambda d: _ts(by_id[d["message_id"]]))
    claimed = set()
    for d in created:
        claimed.add(d["message_id"])
        claimed.update(i for i in d.get("grouped_message_ids", []) if i in by_id)
    out = {}
    for d in created:
        own = by_id[d["message_id"]]
        ids = [d["message_id"]] + [i for i in d.get("grouped_message_ids", []) if i != d["message_id"]]
        known = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
        photos = [m for m in known if m["media_type"] == "image"]
        stamps = [_ts(m) for m in known] or [_ts(own)]
        lo, hi = min(stamps) - PHOTO_WINDOW, max(stamps) + PHOTO_WINDOW
        for m in by_id.values():
            if (m["media_type"] == "image" and m["id"] not in claimed
                    and not (m["text"] or m["caption"]).strip()     # a captioned photo was judged on its own merits
                    and m["chat_jid"] == own["chat_jid"] and lo <= _ts(m) <= hi):
                claimed.add(m["id"])
                photos.append(m)
        out[d["message_id"]] = sorted(photos, key=_ts)
    return out


def _since(args, st, now):
    if args.since:
        m = re.fullmatch(r"(\d+)h", args.since)
        if m:
            return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        except ValueError:
            raise SystemExit(f"--since {args.since!r}: expected <n>h, or an ISO 8601 instant "
                             "such as 2026-09-15T00:00:00Z") from None
        return args.since
    if st["cursor"]:
        c = datetime.fromisoformat(st["cursor"].replace("Z", "+00:00")) - OVERLAP
        return c.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enrich(m, d):
    """Best effort. A voice note whose media expired off WhatsApp's CDN must not
    wedge the run: without this guard the exception propagates, the cursor is
    never written, and that same message is refetched on every run forever."""
    if m["media_type"] == "audio":
        path = ""
        try:
            path = _audio_path(m, d)
            m["text"] = d.transcribe(path) or "[voice note not transcribed]"
        except Exception:  # noqa: BLE001
            m["text"] = "[voice note not transcribed]"
        finally:
            if path and path.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep):
                with contextlib.suppress(OSError):
                    os.remove(path)
    if m["is_group"]:
        try:
            m["context"] = d.group_context(m["chat_jid"], m["id"])
        except Exception:  # noqa: BLE001
            m["context"] = []
    return m


def _audio_path(m, d) -> str:
    """Safe path for a voice note: the synced file if it sits under the wacli store, else a sanitised download."""
    media_root = os.path.realpath(os.path.expanduser(os.environ.get("WACLI_STORE_DIR", "~/.wacli")))
    lp = m["local_path"]
    if lp:
        real = os.path.realpath(lp)
        if real.startswith(media_root + os.sep) and os.path.isfile(real):
            return real
    tmpdir = os.path.realpath(tempfile.gettempdir())
    out = os.path.realpath(os.path.join(tmpdir, f"wa-{_slug(m['id'], 64)}.ogg"))
    if not out.startswith(tmpdir + os.sep):
        raise RuntimeError("invalid media path")
    return d.download_media(m["chat_jid"], m["id"], out)


def process(now, args, d, cfg) -> dict:
    summary = {"seen": 0, "created": 0, "skipped": 0, "errors": 0}
    start, end = cfg["active_hours"]
    if not args.force and not (start <= now.astimezone().hour < end):
        return dict(summary, note="outside active hours")
    if not d.is_authenticated():
        d.notify("wa-inbox", "WhatsApp session lost. Run `wacli auth`, then restart the sync service.")
        _log(d.log_dir, "ERROR not authenticated")
        return dict(summary, errors=1)
    st = state.load(d.state_path)
    fetched = d.list_new(_since(args, st, now))
    high_water = max((m["ts"] for m in fetched), default=None)
    msgs = [m for m in fetched
            if wa.keepable(m) and not state.is_processed(st, m["id"])
            and (cfg["include_groups"] or not m["is_group"])]
    summary["seen"] = len(msgs)
    if not msgs:
        # Move past this window anyway. A batch of nothing but stickers would
        # otherwise pin the cursor forever, hiding every message after it.
        if high_water and not args.dry_run:
            st["cursor"] = high_water
            state.save(d.state_path, st)
        _log(d.log_dir, "run: 0 new messages")
        return summary
    msgs = [_enrich(m, d) for m in msgs]
    token = d.get_token()
    lists = d.list_lists(token)
    default = cfg["default_list"]
    if default not in lists:
        raise RuntimeError(f"default list '{default}' does not exist in Google Tasks; create it or fix config.json")
    open_titles = [t for lid in lists.values() for t in d.open_task_titles(token, lid)]
    decisions = []
    for i in range(0, len(msgs), cfg["batch_size"]):
        decisions += d.classify(classify.build_payload(msgs[i:i + cfg["batch_size"]], list(lists), open_titles))
    by_id = {m["id"]: m for m in msgs}
    photos_for = assign_photos(decisions, by_id)
    for dec in decisions:
        m = by_id[dec["message_id"]]
        tag = ("DRY-CREATE" if dec["create"] else "DRY") if args.dry_run else ("CREATE" if dec["create"] else "skip")
        shown_list = (dec["list"] or default) if dec["create"] else "-"
        _log(d.log_dir, f"{tag} | {m['chat_name']} | {m['sender_name']} | {shown_list} "
                        f"| {dec['title'] or '-'} | {dec['reason']} | {m['text'][:120]!r}")
        if args.dry_run:
            if dec["create"]:
                _log(d.log_dir, f"    photos: {[x['id'] for x in photos_for.get(m['id'], [])] or 'none'}")
            continue
        state.mark_processed(st, m["id"])
        state.save(d.state_path, st)   # before the write: a crash may lose a task, never duplicate one
        if dec["create"]:
            for src in photos_for.get(m["id"], []):
                img = save_image(src, d, cfg["images_dir"])
                if img:
                    dec["notes"] += f"\nPhoto: {img}"
                    _log(d.log_dir, f"    photo: {img}")
                else:
                    _log(d.log_dir, f"    photo: download failed ({src['id']})")
            d.create_task(token, lists.get(dec["list"] or default, lists[default]), dec["title"], dec["notes"])
            summary["created"] += 1
        else:
            summary["skipped"] += 1
    if not args.dry_run:
        st["cursor"] = high_water or max(m["ts"] for m in msgs)
        state.save(d.state_path, st)
    _log(d.log_dir, f"run: {json.dumps(summary)}")
    return summary


def _is_google_auth_error(e) -> bool:
    """A dead Google authorisation needs the user; warn at once instead of after three failures."""
    if isinstance(e, subprocess.CalledProcessError) and e.cmd and "security" in str(e.cmd):
        return True
    return any(m in f"{type(e).__name__} {e}".lower() for m in AUTH_MARKERS)


def real_deps(cfg):
    wa.configure(cfg["wacli_bin"])
    prompt = config.prompt_path(cfg)
    return NS(state_path=config.state_path(), log_dir=config.log_dir(),
              is_authenticated=wa.is_authenticated, list_new=wa.list_new, group_context=wa.group_context,
              download_media=wa.download_media,
              transcribe=lambda p: transcribe.transcribe(p, cfg["whisper_model"], cfg["whisper_language"],
                                                         cfg["ffmpeg_bin"], cfg["whisper_bin"]),
              get_token=gtasks.get_token, list_lists=gtasks.list_lists, open_task_titles=gtasks.open_task_titles,
              create_task=gtasks.create_task,
              classify=lambda payload: classify.classify(payload, cfg, prompt), notify=notify)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wa-inbox", description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="decide and log, write nothing")
    ap.add_argument("--since", help="e.g. 48h or 2026-09-15T00:00:00Z")
    ap.add_argument("--force", action="store_true", help="ignore active hours")
    ap.add_argument("--config", help="path to config.json")
    args = ap.parse_args(argv)
    cfg = config.load(args.config)
    d = real_deps(cfg)
    fails = config.DATA_DIR / ".consecutive_failures"
    try:
        print(json.dumps(process(datetime.now(UTC), args, d, cfg), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        _log(d.log_dir, f"ERROR {type(e).__name__}: {e}")
        fails.parent.mkdir(parents=True, exist_ok=True)
        n = (int(fails.read_text() or 0) + 1) if fails.exists() else 1
        fails.write_text(str(n))
        if _is_google_auth_error(e):
            d.notify("wa-inbox", "Google authorisation expired. Run `wa-inbox setup-google`.")
        elif n >= 3:
            d.notify("wa-inbox", f"{n} consecutive failures: {type(e).__name__}. See logs.")
        sys.exit(1)
    else:
        fails.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
