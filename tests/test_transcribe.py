from unittest.mock import MagicMock, patch

from wa_inbox import transcribe


def test_transcribe_converts_then_runs_whisper(tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        r = MagicMock()
        r.returncode = 0
        r.stdout = " Bonjour, tu peux m'appeler ce soir. \n"
        return r

    with patch("wa_inbox.transcribe.subprocess.run", side_effect=fake_run):
        txt = transcribe.transcribe(str(tmp_path / "a.ogg"), "/m/model.bin", "fr")
    assert txt == "Bonjour, tu peux m'appeler ce soir."
    assert calls[0][0].endswith("ffmpeg") and "-ar" in calls[0] and "16000" in calls[0]
    assert calls[1][0].endswith("whisper-cli") and "-l" in calls[1] and "fr" in calls[1]


def test_transcribe_returns_empty_on_failure(tmp_path):
    r = MagicMock()
    r.returncode = 1
    r.stdout = ""
    r.stderr = "boom"
    with patch("wa_inbox.transcribe.subprocess.run", return_value=r):
        assert transcribe.transcribe(str(tmp_path / "a.ogg"), "/m/model.bin") == ""
