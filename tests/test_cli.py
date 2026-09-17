from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS

from wa_inbox import cli, config, state

MSG = {"id": "M1", "chat_jid": "336@s.whatsapp.net", "chat_name": "Sam", "is_group": False, "sender_jid": "x",
       "sender_name": "Sam", "ts": "2026-09-17T09:00:00Z", "text": "send the contract", "media_type": "",
       "local_path": "", "mime_type": "", "caption": "", "context": []}
DEC = {"message_id": "M1", "create": True, "list": "Acme", "title": "Sam: send the contract", "notes": "n",
       "reason": "r", "grouped_message_ids": []}
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)


def _img(mid, minute, chat="336@s.whatsapp.net"):
    return dict(MSG, id=mid, chat_jid=chat, media_type="image", mime_type="image/jpeg", text="",
                ts=f"2026-09-17T08:{minute:02d}:00Z")


def _txt(mid, minute, text="...", chat="336@s.whatsapp.net"):
    return dict(MSG, id=mid, chat_jid=chat, text=text, ts=f"2026-09-17T08:{minute:02d}:00Z")


def cfg(tmp_path, **over):
    return dict(config.DEFAULTS, images_dir=str(tmp_path / "shots"), context_file="", **over)


def deps(tmp_path, msgs, decisions, authed=True):
    created = []
    d = NS(state_path=tmp_path / "state.json", log_dir=tmp_path / "logs",
           is_authenticated=lambda: authed, list_new=lambda after, limit=500: [dict(m) for m in msgs],
           group_context=lambda c, i: ["Dana: @you?"], download_media=lambda c, i, o: o,
           transcribe=lambda p: "voice text", get_token=lambda: "tok",
           list_lists=lambda t: {"Inbox": "L1", "Acme": "L2"}, open_task_titles=lambda t, lid: [],
           create_task=lambda t, lid, title, notes: created.append((lid, title, notes)) or "T1",
           classify=lambda payload: [dict(decisions[i], message_id=m["id"], grouped_message_ids=[])
                                     for i, m in enumerate(payload["messages"])],
           notify=lambda title, msg: None)
    return d, created


def args(**over):
    base = {"dry_run": False, "since": None, "force": True}
    base.update(over)
    return NS(**base)


def test_creates_a_task_and_advances_the_cursor(tmp_path):
    d, created = deps(tmp_path, [MSG], [DEC])
    s = cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert [c[:2] for c in created] == [("L2", "Sam: send the contract")] and s["created"] == 1
    st = state.load(d.state_path)
    assert st["processed_ids"] == ["M1"] and st["cursor"] == "2026-09-17T09:00:00Z"


def test_empty_list_from_the_model_uses_the_default_list(tmp_path):
    d, created = deps(tmp_path, [MSG], [dict(DEC, list="")])
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert created[0][0] == "L1"


def test_missing_default_list_fails_loudly(tmp_path):
    d, _ = deps(tmp_path, [MSG], [DEC])
    try:
        cli.process(NOW, args(), d, cfg(tmp_path, default_list="Nope"))
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "does not exist in Google Tasks" in str(e)


def test_dry_run_writes_nothing(tmp_path):
    d, created = deps(tmp_path, [MSG], [DEC])
    cli.process(NOW, args(dry_run=True), d, cfg(tmp_path, default_list="Inbox"))
    assert created == [] and not (tmp_path / "state.json").exists()


def test_a_processed_message_is_never_seen_twice(tmp_path):
    d, created = deps(tmp_path, [MSG], [DEC])
    state.save(d.state_path, {"cursor": None, "processed_ids": ["M1"]})
    assert cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))["seen"] == 0
    assert created == []


def test_the_cursor_moves_even_when_a_window_holds_nothing_usable(tmp_path):
    """A batch of stickers must not pin the cursor and hide everything after it."""
    sticker = dict(MSG, id="S1", text="", media_type="sticker", ts="2026-09-17T09:30:00Z")
    d, created = deps(tmp_path, [sticker], [])
    s = cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert s["seen"] == 0 and created == []
    assert state.load(d.state_path)["cursor"] == "2026-09-17T09:30:00Z"


def test_a_group_message_still_moves_the_cursor_when_groups_are_off(tmp_path):
    group = dict(MSG, id="G1", chat_jid="1@g.us", is_group=True, ts="2026-09-17T09:40:00Z")
    d, _ = deps(tmp_path, [group], [DEC])
    assert cli.process(NOW, args(), d, cfg(tmp_path, include_groups=False))["seen"] == 0
    assert state.load(d.state_path)["cursor"] == "2026-09-17T09:40:00Z"


def test_an_expired_voice_note_does_not_wedge_the_run(tmp_path):
    """Media that fell off WhatsApp's CDN must degrade, not block the cursor forever."""
    voice = dict(MSG, id="V1", media_type="audio", local_path="", text="[Audio]")
    d, created = deps(tmp_path, [voice], [dict(DEC, create=False)])

    def gone(chat, mid, out):
        raise RuntimeError("wacli media download failed: 410 gone")

    d.download_media = gone
    seen = {}
    d.classify = lambda payload: seen.update(payload) or [dict(DEC, message_id="V1", create=False,
                                                              grouped_message_ids=[])]
    s = cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert s["errors"] == 0 and seen["messages"][0]["text"] == "[voice note not transcribed]"
    assert state.load(d.state_path)["cursor"] == "2026-09-17T09:00:00Z"


def test_a_message_is_marked_processed_before_the_task_is_created(tmp_path):
    """Crash-safety: losing a task is acceptable, creating it twice is not."""
    order = []
    d, _ = deps(tmp_path, [MSG], [DEC])
    d.create_task = lambda t, lid, title, notes: order.append(
        ("create", state.load(d.state_path)["processed_ids"])) or "T1"
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert order == [("create", ["M1"])]


def test_a_captioned_photo_is_never_swept_into_a_neighbouring_task():
    """The classifier judged it on its own merits; do not override that."""
    msgs = [_txt("A", 0, "fix this"), dict(_img("P", 2), text="look at my holiday")]
    got = cli.assign_photos([dict(DEC, message_id="A", create=True, grouped_message_ids=[])],
                            {m["id"]: m for m in msgs})
    assert got["A"] == []


def test_outside_active_hours_nothing_is_read(tmp_path):
    d, _ = deps(tmp_path, [MSG], [DEC])
    s = cli.process(datetime(2026, 9, 17, 3, 0, tzinfo=UTC), args(force=False), d,
                    cfg(tmp_path, active_hours=[7, 23]))
    assert s["note"] == "outside active hours" and s["seen"] == 0


def test_groups_can_be_switched_off(tmp_path):
    group = dict(MSG, id="G1", chat_jid="1@g.us", is_group=True)
    d, _ = deps(tmp_path, [group], [DEC])
    assert cli.process(NOW, args(), d, cfg(tmp_path, include_groups=False))["seen"] == 0


def test_voice_notes_are_transcribed_and_groups_get_context(tmp_path):
    voice = dict(MSG, id="V1", chat_jid="1@g.us", is_group=True, text="[Audio]", media_type="audio",
                 local_path="/x/a.ogg")
    seen = {}
    d, _ = deps(tmp_path, [voice], [dict(DEC, create=False)])
    d.classify = lambda payload: seen.update(payload) or [dict(DEC, message_id="V1", create=False,
                                                               grouped_message_ids=[])]
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert seen["messages"][0]["text"] == "voice text" and seen["messages"][0]["context"] == ["Dana: @you?"]


def test_batches_are_split(tmp_path):
    msgs = [dict(MSG, id=f"M{i}", ts=f"2026-09-17T09:{i:02d}:00Z") for i in range(25)]
    sizes = []
    d, _ = deps(tmp_path, msgs, [])
    d.classify = lambda payload: sizes.append(len(payload["messages"])) or [
        dict(DEC, message_id=m["id"], create=False, grouped_message_ids=[]) for m in payload["messages"]]
    cli.process(NOW, args(), d, cfg(tmp_path, batch_size=10, default_list="Inbox"))
    assert sizes == [10, 10, 5]


def test_lost_session_notifies_and_stops(tmp_path):
    calls = []
    d, created = deps(tmp_path, [MSG], [DEC], authed=False)
    d.notify = lambda t, m: calls.append(m)
    s = cli.process(NOW, args(), d, cfg(tmp_path))
    assert calls and s["errors"] == 1 and created == []


def test_declared_grouped_photos_are_attached(tmp_path):
    photo1 = dict(MSG, id="P1", media_type="image", mime_type="image/jpeg", text="")
    photo2 = dict(MSG, id="P2", media_type="image", mime_type="image/png", text="")
    voice = dict(MSG, id="V1", media_type="audio", local_path="/x/a.ogg", text="[Audio]")
    d, created = deps(tmp_path, [photo1, photo2, voice], [])
    d.download_media = lambda c, i, o: (Path(o).write_bytes(b"x"), o)[1]
    d.classify = lambda payload: [
        dict(DEC, message_id="P1", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="P2", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="V1", create=True, notes="n", grouped_message_ids=["P1", "P2"])]
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert len(created) == 1 and created[0][2].count("\nPhoto: ") == 2


def test_a_request_spread_over_several_photos_keeps_them_all():
    """One complaint, two shots twenty minutes apart, only one declared by the model."""
    msgs = [_img("P1", 8), _txt("T1", 8, "too zoomed"), _img("P2", 28), _txt("V1", 28, "and the head is off")]
    by_id = {m["id"]: m for m in msgs}
    decisions = [
        dict(DEC, message_id="P1", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="T1", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="P2", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="V1", create=True, grouped_message_ids=["P1", "T1"]),
    ]
    got = cli.assign_photos(decisions, by_id)
    assert [m["id"] for m in got["V1"]] == ["P1", "P2"], "the undeclared photo must still be attached"


def test_two_tasks_in_one_chat_never_share_a_photo():
    msgs = [_img("P1", 0), _txt("A", 0), _img("P2", 40), _txt("B", 40)]
    by_id = {m["id"]: m for m in msgs}
    decisions = [
        dict(DEC, message_id="A", create=True, grouped_message_ids=["P1"]),
        dict(DEC, message_id="B", create=True, grouped_message_ids=["P2"]),
        dict(DEC, message_id="P1", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="P2", create=False, grouped_message_ids=[]),
    ]
    got = cli.assign_photos(decisions, by_id)
    assert [m["id"] for m in got["A"]] == ["P1"] and [m["id"] for m in got["B"]] == ["P2"]


def test_a_distant_photo_is_left_alone():
    msgs = [_txt("A", 0), _img("FAR", 59)]
    got = cli.assign_photos([dict(DEC, message_id="A", create=True, grouped_message_ids=[])],
                            {m["id"]: m for m in msgs})
    assert got["A"] == []


def test_a_photo_from_another_chat_is_never_borrowed():
    msgs = [_txt("A", 0), _img("OTHER", 0, chat="999@g.us")]
    got = cli.assign_photos([dict(DEC, message_id="A", create=True, grouped_message_ids=[])],
                            {m["id"]: m for m in msgs})
    assert got["A"] == []


def test_every_attached_photo_gets_its_own_line_in_the_notes(tmp_path):
    msgs = [_img("P1", 8), _img("P2", 10), _txt("V1", 10, "fix this")]
    d, created = deps(tmp_path, msgs, [])
    d.download_media = lambda c, i, o: (Path(o).write_bytes(b"x"), o)[1]
    d.classify = lambda payload: [
        dict(DEC, message_id="P1", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="P2", create=False, grouped_message_ids=[]),
        dict(DEC, message_id="V1", create=True, notes="n", grouped_message_ids=["P1"])]
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert len(created) == 1 and created[0][2].count("\nPhoto: ") == 2


def test_photo_path_is_sanitised_and_contained(tmp_path):
    asked = []
    d, _ = deps(tmp_path, [], [])
    d.download_media = lambda c, i, o: asked.append(o) or o
    m = dict(MSG, id="../../etc/passwd", media_type="image", mime_type="image/png")
    out = cli.save_image(m, d, str(tmp_path / "shots"))
    assert out.startswith(str(tmp_path / "shots")) and ".." not in out and out.endswith(".png")


def test_photos_can_be_disabled(tmp_path):
    d, _ = deps(tmp_path, [], [])
    assert cli.save_image(dict(MSG, media_type="image"), d, "") == ""


def test_a_failed_photo_download_leaves_the_task_intact(tmp_path):
    def boom(c, i, o):
        raise RuntimeError("cdn 403")

    d, created = deps(tmp_path, [dict(MSG, media_type="image", mime_type="image/jpeg")], [DEC])
    d.download_media = boom
    cli.process(NOW, args(), d, cfg(tmp_path, default_list="Inbox"))
    assert created[0][2] == "n"


def test_google_auth_errors_are_flagged_immediately():
    import subprocess as sp
    from urllib.error import HTTPError
    assert cli._is_google_auth_error(RuntimeError("invalid_grant: Token has been expired or revoked."))
    assert cli._is_google_auth_error(HTTPError("u", 401, "Unauthorized", None, None))
    assert cli._is_google_auth_error(sp.CalledProcessError(44, ["security", "find-generic-password"]))
    assert not cli._is_google_auth_error(RuntimeError("wacli messages list failed: store locked"))
