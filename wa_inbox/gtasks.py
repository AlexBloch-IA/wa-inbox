"""Google Tasks API v1. The OAuth refresh token lives in the macOS keychain
(service "wa-inbox", written by `wa-inbox setup-google`). Standard library only."""
import json
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TASKS_API = "https://tasks.googleapis.com/tasks/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
KEYCHAIN_SERVICE = "wa-inbox"


def _keychain_secret() -> dict:
    out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip())


def get_token() -> str:
    c = _keychain_secret()
    body = urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                      "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urlopen(Request(TOKEN_URL, data=body), timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def _call(token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{TASKS_API}{path}", data=data, method=method,
                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def _paged(token, path) -> list:
    """Follow nextPageToken. Without this, someone with 100+ open tasks silently
    loses duplicate detection on everything past the first page."""
    items, page, guard = [], None, 0
    while guard < 50:
        guard += 1
        out = _call(token, "GET", path + (f"&pageToken={page}" if page else ""))
        items += out.get("items", [])
        page = out.get("nextPageToken")
        if not page:
            break
    return items


def list_lists(token) -> dict:
    return {it["title"]: it["id"] for it in _paged(token, "/users/@me/lists?maxResults=100")}


def open_task_titles(token, list_id) -> list:
    items = _paged(token, f"/lists/{list_id}/tasks?showCompleted=false&maxResults=100")
    return [it["title"] for it in items if it.get("title")]


def create_task(token, list_id, title, notes) -> str:
    return _call(token, "POST", f"/lists/{list_id}/tasks", {"title": title, "notes": notes})["id"]
