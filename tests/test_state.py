from wa_inbox import state


def test_load_missing_gives_empty(tmp_path):
    s = state.load(tmp_path / "state.json")
    assert s == {"cursor": None, "processed_ids": []}


def test_save_is_atomic_and_roundtrips(tmp_path):
    p = tmp_path / "state.json"
    s = {"cursor": "2026-09-17T10:00:00Z", "processed_ids": ["A"]}
    state.save(p, s)
    assert not list(tmp_path.glob("*.tmp"))
    assert state.load(p) == s


def test_mark_processed_caps_at_5000():
    s = {"cursor": None, "processed_ids": [str(i) for i in range(5000)]}
    state.mark_processed(s, "new")
    assert len(s["processed_ids"]) == 5000 and s["processed_ids"][-1] == "new" and "0" not in s["processed_ids"]
    assert state.is_processed(s, "new") and not state.is_processed(s, "zzz")
