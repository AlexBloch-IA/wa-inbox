"""One-time OAuth: exchange a Desktop client JSON for a refresh token kept in the macOS keychain."""
import json
import secrets
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .gtasks import KEYCHAIN_SERVICE, TASKS_API

SCOPE = "https://www.googleapis.com/auth/tasks"
PORT = 8765


def _store_in_keychain(secret) -> None:
    """Write the secret over stdin, never in argv, so it cannot be read from `ps`.

    `security -w` with no value prompts twice, so the value is sent twice.
    """
    subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE], capture_output=True)
    subprocess.run(["security", "add-generic-password", "-a", "wa-inbox", "-s", KEYCHAIN_SERVICE, "-U", "-w"],
                   input=f"{secret}\n{secret}\n", text=True, capture_output=True, check=True)


def main(argv):
    if len(argv) != 1:
        sys.exit("usage: wa-inbox setup-google <client_secret_xxx.json>")
    cfg = json.loads(Path(argv[0]).read_text())["installed"]
    state = secrets.token_urlsafe(16)
    redirect = f"http://localhost:{PORT}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": cfg["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("localhost", PORT), Handler)
    print("Opening your browser. Pick your Google account, then click through the "
          "'Google hasn't verified this app' screen via Advanced.")
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if "error" in got or got.get("state") != state:
        sys.exit(f"authorisation failed: {got.get('error', 'state mismatch')}")
    body = urlencode({"code": got["code"], "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                      "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    tok = json.loads(urlopen(Request("https://oauth2.googleapis.com/token", data=body), timeout=30).read())
    if "refresh_token" not in tok:
        sys.exit(f"no refresh_token in the response (keys: {sorted(tok)}). "
                 "Revoke the app at https://myaccount.google.com/permissions and try again.")
    secret = json.dumps({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                         "refresh_token": tok["refresh_token"]})
    _store_in_keychain(secret)
    lists = json.loads(urlopen(Request(f"{TASKS_API}/users/@me/lists",
                                       headers={"Authorization": f"Bearer {tok['access_token']}"}),
                               timeout=30).read()).get("items", [])
    print(f"Refresh token stored in the keychain under '{KEYCHAIN_SERVICE}'.")
    print("Your Google Tasks lists:", [i["title"] for i in lists])
