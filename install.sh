#!/bin/bash
# wa-inbox installer. Interactive, idempotent, macOS only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${WA_INBOX_CONFIG_DIR:-$HOME/.config/wa-inbox}"
DATA_DIR="${WA_INBOX_DATA_DIR:-$HOME/.local/share/wa-inbox}"
LOGS="$DATA_DIR/logs"
BIN_DIR="$HOME/.local/bin"
AGENTS="$HOME/Library/LaunchAgents"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }
die()  { printf '\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }
ask()  { read -r -p "    $1 [y/N] " a; [[ "$a" == [yY] ]]; }

[[ "$(uname)" == "Darwin" ]] || die "wa-inbox is macOS only."

say "1/7 Dependencies"
command -v brew >/dev/null || die "Homebrew is required: https://brew.sh"
command -v wacli >/dev/null || { say "Installing wacli"; brew tap openclaw/tap && brew install openclaw/tap/wacli; }
command -v ffmpeg >/dev/null || { say "Installing ffmpeg"; brew install ffmpeg; }
command -v whisper-cli >/dev/null || { say "Installing whisper-cpp"; brew install whisper-cpp; }
command -v claude >/dev/null || die "Claude Code CLI not found. Install it from https://claude.com/claude-code and sign in, then rerun."
PYTHON="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required, found $($PYTHON --version). Try: brew install python"
printf '    wacli %s\n    python %s\n' "$(wacli --version | awk '{print $2}')" "$("$PYTHON" --version | awk '{print $2}')"

say "2/7 Directories and launcher"
mkdir -p "$CONFIG_DIR" "$DATA_DIR/models" "$LOGS" "$BIN_DIR"
cat > "$BIN_DIR/wa-inbox" <<LAUNCHER
#!/bin/bash
export PYTHONPATH="$REPO"
exec "$PYTHON" -m wa_inbox "\$@"
LAUNCHER
chmod +x "$BIN_DIR/wa-inbox"
printf '    installed %s\n' "$BIN_DIR/wa-inbox"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH. Add it to ~/.zshrc." ;; esac

say "3/7 Configuration"
if [[ -f "$CONFIG_DIR/config.json" ]]; then
  printf '    %s already exists, left untouched.\n' "$CONFIG_DIR/config.json"
else
  PYTHONPATH="$REPO" "$PYTHON" -m wa_inbox init
fi
warn "Edit $CONFIG_DIR/config.json (default_list must be an EXISTING Google Tasks list)."
warn "Edit $CONFIG_DIR/context.md to tell the classifier who you are and which list is which."

say "4/7 Whisper model (voice notes, ~466 MB, local)"
MODEL="$DATA_DIR/models/ggml-small.bin"
if [[ -f "$MODEL" ]]; then
  printf '    already downloaded.\n'
elif ask "Download the whisper model now?"; then
  # --fail and a temp file: an interrupted download must not leave a truncated
  # model that every later run mistakes for a working one.
  if curl -L --fail --progress-bar -o "$MODEL.part" "$MODEL_URL"; then
    mv "$MODEL.part" "$MODEL"
  else
    rm -f "$MODEL.part"
    warn "Download failed. Voice notes will not be transcribed until you retry."
  fi
else
  warn "Skipped. Voice notes will not be transcribed until you download it to $MODEL."
fi

say "5/7 Pair WhatsApp"
if wacli --read-only auth status --json 2>/dev/null | grep -q '"authenticated":true'; then
  printf '    already paired.\n'
else
  warn "A QR code will appear. On your phone: WhatsApp > Settings > Linked Devices > Link a Device."
  warn "Let the first history sync finish; it stops on its own. This can take several minutes."
  ask "Start pairing now?" && WACLI_SYNC_MAX_DB_SIZE=500MB wacli auth || warn "Skipped. Run 'wacli auth' later."
  chmod 700 "$HOME/.wacli" 2>/dev/null || true
fi

say "6/7 Authorise Google Tasks"
if security find-generic-password -s wa-inbox >/dev/null 2>&1; then
  printf '    keychain entry already present.\n'
else
  warn "Follow docs/google-setup.md to create an OAuth Desktop client and download its JSON."
  warn "Then run: wa-inbox setup-google ~/Downloads/client_secret_*.json"
fi

say "7/7 Background services"
PATH_LINE="$(printf '%s\n' \
  "$(dirname "$PYTHON")" "$(dirname "$(command -v wacli)")" "$(dirname "$(command -v claude)")" \
  "$(dirname "$(command -v ffmpeg)")" "$(dirname "$(command -v whisper-cli)")" \
  /usr/bin /bin /usr/sbin /sbin | awk '!seen[$0]++' | paste -sd: -)"
mkdir -p "$AGENTS"
for label in sync run; do
  sed -e "s|__HOME__|$HOME|g" -e "s|__REPO__|$REPO|g" -e "s|__LOGS__|$LOGS|g" \
      -e "s|__PYTHON__|$PYTHON|g" -e "s|__WACLI__|$(command -v wacli)|g" -e "s|__PATH__|$PATH_LINE|g" \
      "$REPO/launchd/sh.wa-inbox.$label.plist.template" > "$AGENTS/sh.wa-inbox.$label.plist"
  plutil -lint "$AGENTS/sh.wa-inbox.$label.plist" >/dev/null || die "generated plist is invalid: $label"
done
printf '    wrote %s/sh.wa-inbox.{sync,run}.plist\n' "$AGENTS"
if ask "Load the services now? (say no until the dry run looks right)"; then
  for label in sync run; do
    launchctl bootout "gui/$(id -u)/sh.wa-inbox.$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/sh.wa-inbox.$label.plist"
  done
  launchctl list | grep wa-inbox || true
else
  warn "Load them later with:"
  warn "  launchctl bootstrap gui/\$(id -u) $AGENTS/sh.wa-inbox.sync.plist"
  warn "  launchctl bootstrap gui/\$(id -u) $AGENTS/sh.wa-inbox.run.plist"
fi

say "Done"
cat <<NEXT
    Next:
      1. Edit $CONFIG_DIR/config.json and $CONFIG_DIR/context.md
      2. wa-inbox setup-google ~/Downloads/client_secret_*.json   (if not done)
      3. wa-inbox --dry-run --since 48h --force                   (writes nothing)
      4. Read the decisions:  tail -50 $LOGS/\$(date +%F).log
      5. Happy with them? Load the services (step 7 above).
NEXT
