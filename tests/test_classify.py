import json
from unittest.mock import MagicMock, patch

from wa_inbox import classify, config

MSGS = [{"id": "M1", "chat_jid": "336@s.whatsapp.net", "chat_name": "Sam", "is_group": False,
         "sender_jid": "336@s.whatsapp.net", "sender_name": "Sam", "ts": "2026-09-17T09:00:00Z",
         "text": "Can you send the contract?", "media_type": "", "local_path": "", "mime_type": "",
         "caption": "", "context": []}]
CFG = dict(config.DEFAULTS, context_file="", claude_bin="claude")


def _prompt():
    return config.prompt_path(CFG)


def _result(decisions):
    r = MagicMock()
    r.returncode = 0
    r.stdout = json.dumps({"type": "result", "structured_output": {"decisions": decisions}})
    return r


def test_build_payload_shape():
    p = classify.build_payload(MSGS, ["Inbox", "Acme"], ["Call Tim"])
    assert p["lists"] == ["Inbox", "Acme"] and p["open_tasks"] == ["Call Tim"]
    assert p["messages"][0] == {"id": "M1", "chat": "Sam", "is_group": False, "sender": "Sam",
                                "date": "2026-09-17T09:00:00Z", "text": "Can you send the contract?",
                                "is_voice": False, "has_image": False, "context": []}


def test_runs_claude_with_no_tools_in_a_sandbox_and_delimits_the_payload():
    dec = [{"message_id": "M1", "create": True, "list": "Acme", "title": "Sam: send the contract",
            "notes": "n", "reason": "request", "grouped_message_ids": []}]
    with patch("wa_inbox.classify.subprocess.run", return_value=_result(dec)) as run:
        out = classify.classify(classify.build_payload(MSGS, ["Inbox", "Acme"], []), CFG, _prompt())
    cmd, kwargs = run.call_args[0][0], run.call_args[1]
    assert "--model" in cmd and CFG["model"] in cmd and "--json-schema" in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "", "the classifier must get no tools"
    assert "wa-inbox-" in kwargs["cwd"], "it must run in a throwaway directory, not the user's home"
    assert "<messages>" in cmd[-1] and "</messages>" in cmd[-1]
    assert out == dec


def test_missing_decision_raises():
    with patch("wa_inbox.classify.subprocess.run", return_value=_result([])):
        try:
            classify.classify(classify.build_payload(MSGS, ["Inbox"], []), CFG, _prompt())
            raise AssertionError("should have raised")
        except RuntimeError as e:
            assert "M1" in str(e)


def test_unknown_list_falls_back_to_the_default():
    dec = [{"message_id": "M1", "create": True, "list": "Nope", "title": "x", "notes": "y",
            "reason": "z", "grouped_message_ids": []}]
    with patch("wa_inbox.classify.subprocess.run", return_value=_result(dec)):
        out = classify.classify(classify.build_payload(MSGS, ["Inbox"], []), CFG, _prompt())
    assert out[0]["list"] == "" and "unknown list" in out[0]["reason"]


def test_model_output_is_capped_and_normalised():
    dec = [{"message_id": "M1", "create": True, "list": "Inbox", "title": "t" * 200,
            "notes": "n" * 5000, "reason": "z"}]
    with patch("wa_inbox.classify.subprocess.run", return_value=_result(dec)):
        out = classify.classify(classify.build_payload(MSGS, ["Inbox"], []), CFG, _prompt())
    assert len(out[0]["title"]) == 80 and len(out[0]["notes"]) == classify.MAX_NOTES
    assert out[0]["grouped_message_ids"] == []


def test_context_file_is_appended_to_the_system_prompt(tmp_path):
    ctx = tmp_path / "context.md"
    ctx.write_text("I am Jane and Acme is my client.")
    prompt = classify._system_prompt(dict(CFG, context_file=str(ctx)), _prompt())
    assert "Acme is my client" in prompt and "create=true" in prompt


def test_the_classifier_is_actually_stripped_of_its_tools():
    """`--allowedTools ""` only pre-approves an empty list, it removes nothing.
    Verified on 2026-09-17: without --restricted the subprocess ran `id -un`."""
    dec = [{"message_id": "M1", "create": False, "list": "", "title": "", "notes": "",
            "reason": "no action", "grouped_message_ids": []}]
    with patch("wa_inbox.classify.subprocess.run", return_value=_result(dec)) as run:
        classify.classify(classify.build_payload(MSGS, ["Inbox"], []), CFG, _prompt())
    cmd = run.call_args[0][0]
    assert "--restricted" in cmd, "without this the classifier can still reach Bash"
    assert "--strict-mcp-config" in cmd, "otherwise it inherits the user's MCP servers"
    denied = cmd[cmd.index("--disallowedTools") + 1]
    for tool in ("Bash", "Read", "Write", "Edit", "WebFetch", "Agent"):
        assert tool in denied
