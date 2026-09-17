"""Configuration loading. One JSON file, every field optional, sane defaults."""
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("WA_INBOX_CONFIG_DIR", Path.home() / ".config" / "wa-inbox"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("WA_INBOX_DATA_DIR", Path.home() / ".local" / "share" / "wa-inbox"))
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent

DEFAULTS = {
    # Google Tasks list used when the classifier is unsure. Must already exist.
    "default_list": "Inbox",
    # Where photos attached to a task are stored. "" disables photo handling.
    "images_dir": str(Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "wa-inbox"),
    # Local hours during which runs happen, [start, end). Outside it, a run exits at once.
    "active_hours": [7, 23],
    # Messages per classifier call.
    "batch_size": 50,
    "model": "claude-sonnet-5",
    # Built-in prompt to use: "en" or "fr".
    "language": "en",
    # Optional file describing you, your projects and which list they map to.
    "context_file": str(CONFIG_DIR / "context.md"),
    "whisper_model": str(DATA_DIR / "models" / "ggml-small.bin"),
    # Whisper language code, or "auto".
    "whisper_language": "auto",
    # Read group chats too (only messages that address you become tasks).
    "include_groups": True,
    # Binaries, overridable when Homebrew is elsewhere.
    "wacli_bin": "wacli",
    "claude_bin": "claude",
    "ffmpeg_bin": "ffmpeg",
    "whisper_bin": "whisper-cli",
}


def _expand(value):
    return os.path.expanduser(value) if isinstance(value, str) and value.startswith("~") else value


def load(path=None) -> dict:
    p = Path(path or CONFIG_PATH)
    user = json.loads(p.read_text()) if p.exists() else {}
    unknown = set(user) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown config keys in {p}: {sorted(unknown)}")
    cfg = {k: _expand(user.get(k, v)) for k, v in DEFAULTS.items()}
    _validate(cfg)
    return cfg


def _validate(cfg) -> None:
    hours = cfg["active_hours"]
    if (not isinstance(hours, list) or len(hours) != 2
            or not all(isinstance(h, int) and 0 <= h <= 24 for h in hours)):
        raise ValueError("active_hours must be two integers between 0 and 24, e.g. [7, 23]")
    if hours[0] >= hours[1]:
        raise ValueError(f"active_hours {hours} never opens; the window does not wrap past midnight. "
                         "Use [0, 24] to run at any hour.")
    if not isinstance(cfg["batch_size"], int) or cfg["batch_size"] < 1:
        raise ValueError("batch_size must be a positive integer")
    if cfg["language"] not in ("en", "fr"):
        raise ValueError("language must be 'en' or 'fr'")
    if not isinstance(cfg["include_groups"], bool):
        raise ValueError("include_groups must be true or false")
    if not str(cfg["default_list"]).strip():
        raise ValueError("default_list must name an existing Google Tasks list")


def prompts_dir() -> Path:
    """Inside the package when pip-installed, at the repo root when run from a clone."""
    packaged = PACKAGE_ROOT / "prompts"
    return packaged if packaged.is_dir() else REPO_ROOT / "prompts"


def prompt_path(cfg) -> Path:
    return prompts_dir() / f"classify.{cfg['language']}.md"


def state_path() -> Path:
    return DATA_DIR / "state.json"


def log_dir() -> Path:
    return DATA_DIR / "logs"


def write_default(path=None) -> Path:
    p = Path(path or CONFIG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(DEFAULTS, indent=2) + "\n")
    return p
