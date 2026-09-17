"""WhatsApp voice note (.ogg/opus) to text, fully local: ffmpeg then whisper-cli.

No audio ever leaves the machine.
"""
import contextlib
import os
import subprocess
import tempfile
from pathlib import Path


def transcribe(audio_path, model, language="auto", ffmpeg="ffmpeg", whisper="whisper-cli") -> str:
    wav = os.path.join(tempfile.gettempdir(), Path(audio_path).stem + ".wav")
    try:
        r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", audio_path, "-ar", "16000", "-ac", "1", wav],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return ""
        r = subprocess.run([whisper, "-m", model, "-l", language, "-nt", "--no-prints", "-f", wav],
                           capture_output=True, text=True, timeout=300)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""
    finally:
        with contextlib.suppress(OSError):
            os.remove(wav)
