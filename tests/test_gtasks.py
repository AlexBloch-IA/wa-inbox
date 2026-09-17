import json
from unittest.mock import MagicMock, patch

from wa_inbox import gtasks


def _resp(payload):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    return m


def test_list_lists_maps_title_to_id():
    items = {"items": [{"id": "L1", "title": "Inbox"}, {"id": "L2", "title": "Acme"}]}
    with patch("wa_inbox.gtasks.urlopen", return_value=_resp(items)):
        assert gtasks.list_lists("tok") == {"Inbox": "L1", "Acme": "L2"}


def test_open_task_titles_skips_completed_and_empty():
    items = {"items": [{"title": "Call Tim", "status": "needsAction"}, {"title": "", "status": "needsAction"}]}
    with patch("wa_inbox.gtasks.urlopen", return_value=_resp(items)):
        assert gtasks.open_task_titles("tok", "L1") == ["Call Tim"]


def test_create_task_posts_title_and_notes():
    with patch("wa_inbox.gtasks.urlopen", return_value=_resp({"id": "T9"})) as u:
        assert gtasks.create_task("tok", "L1", "Sam: send X", "notes") == "T9"
        req = u.call_args[0][0]
        assert req.full_url.endswith("/lists/L1/tasks")
        assert json.loads(req.data) == {"title": "Sam: send X", "notes": "notes"}


def test_get_token_refreshes_from_keychain():
    secret = {"client_id": "c", "client_secret": "s", "refresh_token": "r"}
    with patch("wa_inbox.gtasks._keychain_secret", return_value=secret), \
         patch("wa_inbox.gtasks.urlopen", return_value=_resp({"access_token": "AT"})) as u:
        assert gtasks.get_token() == "AT"
        req = u.call_args[0][0]
        assert req.full_url == gtasks.TOKEN_URL
        assert b"grant_type=refresh_token" in req.data and b"refresh_token=r" in req.data


def test_keychain_write_never_puts_the_secret_in_argv():
    from unittest.mock import call  # noqa: F401

    from wa_inbox import setup_google
    with patch("wa_inbox.setup_google.subprocess.run") as run:
        setup_google._store_in_keychain('{"refresh_token": "SECRET"}')
    write = run.call_args_list[-1]
    assert "SECRET" not in " ".join(write[0][0]), "the secret must not appear in the argument vector"
    assert "SECRET" in write[1]["input"] and write[1]["input"].count("SECRET") == 2
