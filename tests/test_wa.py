import json
from unittest.mock import patch

from wa_inbox import wa


def _m(msg_id, chat, name, text, **over):
    row = {"ChatJID": chat, "ChatName": name, "MsgID": msg_id, "SenderJID": chat, "SenderName": name,
           "Timestamp": f"2026-09-17T09:0{msg_id[-1]}:00Z", "FromMe": False, "Text": text,
           "MediaType": "", "LocalPath": ""}
    row.update(over)
    return row


DM = "336@s.whatsapp.net"
GROUP = "1203@g.us"
RAW = {"messages": [
    _m("M1", DM, "Sam", "Can you send the contract?"),
    _m("M2", GROUP, "Team", "[Audio]", SenderName="Dana", MediaType="audio", LocalPath="/x/a.ogg"),
    _m("M3", GROUP, "Team", "ok", FromMe=True),
    _m("M4", "99@newsletter", "News", "promo"),
    _m("M5", DM, "Sam", "", MediaType="image"),
]}


def test_list_new_normalises_and_filters():
    with patch("wa_inbox.wa._wacli", return_value=json.dumps(RAW)) as w:
        msgs = wa.list_new("2026-09-17T08:00:00Z")
    args = w.call_args[0][0]
    assert args[:3] == ["messages", "list", "--json"] and "--from-them" in args and "--after" in args
    assert [m["id"] for m in msgs] == ["M1", "M2", "M4", "M5"]   # M3 is ours, nothing else is filtered here
    assert [m["id"] for m in msgs if wa.keepable(m)] == ["M1", "M2", "M5"]   # M4 is a newsletter
    assert msgs[0]["is_group"] is False and msgs[1]["is_group"] is True
    assert msgs[1]["local_path"] == "/x/a.ogg" and msgs[1]["media_type"] == "audio"


def test_is_authenticated_reads_json():
    ok = '{"success": true, "data": {"authenticated": true, "phone": "x"}, "error": null}'
    with patch("wa_inbox.wa._wacli", return_value=ok):
        assert wa.is_authenticated() is True
    with patch("wa_inbox.wa._wacli", return_value='{"authenticated": true}'):
        assert wa.is_authenticated() is True
    with patch("wa_inbox.wa._wacli", return_value='{"success": true, "data": {"logged_out": true}, "error": null}'):
        assert wa.is_authenticated() is False


def test_list_new_unwraps_envelope():
    env = {"success": True, "data": RAW, "error": None}
    with patch("wa_inbox.wa._wacli", return_value=json.dumps(env)):
        assert [m["id"] for m in wa.list_new(None) if wa.keepable(m)] == ["M1", "M2", "M5"]


def test_group_context_returns_texts_of_previous_messages():
    ctx = {"messages": [
        {"MsgID": "A", "SenderName": "Dana", "Text": "@you can you handle it?", "FromMe": False},
        {"MsgID": "M2", "SenderName": "Dana", "Text": "[Audio]", "FromMe": False},
    ]}
    with patch("wa_inbox.wa._wacli", return_value=json.dumps(ctx)):
        assert wa.group_context(GROUP, "M2") == ["Dana: @you can you handle it?"]


def test_env_is_read_only():
    assert wa.ENV["WACLI_READONLY"] == "1"
