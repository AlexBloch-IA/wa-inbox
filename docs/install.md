# Install

macOS only. Budget 30 minutes, most of it waiting for the first WhatsApp history sync.

## 1. Clone and run the installer

```bash
git clone https://github.com/AlexBloch-IA/wa-inbox.git
cd wa-inbox
./install.sh
```

The installer is interactive and safe to run again. It never overwrites an existing
`config.json`, and it asks before pairing WhatsApp or loading the background services.

It walks through seven steps:

1. **Dependencies.** Installs `wacli`, `ffmpeg` and `whisper-cpp` through Homebrew if they
   are missing. It stops if the Claude Code CLI is absent, because there is no way to
   install and sign into it unattended.
2. **Directories and launcher.** Creates `~/.config/wa-inbox`, `~/.local/share/wa-inbox`
   and a `wa-inbox` launcher in `~/.local/bin`. Add that directory to your `PATH` if the
   installer warns you it is missing.
3. **Configuration.** Writes a default `config.json` and a starter `context.md`.
4. **Whisper model.** Downloads `ggml-small.bin`, about 466 MB, used to transcribe voice
   notes on your machine. Skip it if you do not care about voice notes.
5. **WhatsApp pairing.** Shows a QR code. On your phone: WhatsApp, Settings, Linked
   Devices, Link a Device. The first history sync then runs until it goes idle and stops
   on its own; leave the window open until it does.
6. **Google authorisation.** Points you at [google-setup.md](google-setup.md), which is
   the long part. Come back and run `wa-inbox setup-google` when you have the client JSON.
7. **Background services.** Generates and optionally loads two launchd agents.

## 2. Configure before the first real run

Two files matter.

`~/.config/wa-inbox/config.json` — `default_list` must be the exact name of a Google Tasks
list that **already exists**. The tool never creates lists. Set `language` to `fr` if you
want French task titles.

`~/.config/wa-inbox/context.md` — a page describing who you are, which lists you keep and
what belongs in each. The classifier reads it to route tasks. Without it everything lands
in the default list, which still works but is less useful.

## 3. Dry run before you trust it

```bash
wa-inbox --dry-run --since 48h --force
tail -50 ~/.local/share/wa-inbox/logs/$(date +%F).log
```

Nothing is written to Google Tasks. Each line shows the decision, the list, the title and
the reason. Read them. If the triage is wrong, edit the prompt in `prompts/` or add detail
to `context.md`, then run it again. Tune the prompt, not the code.

## 4. Go live

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/sh.wa-inbox.sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/sh.wa-inbox.run.plist
launchctl list | grep wa-inbox
```

The sync agent keeps a WhatsApp connection open and restarts whenever you log in. The run
agent fires at minute 0 and minute 30, and exits immediately outside your configured
active hours.

## 5. Check it stayed invisible

Open WhatsApp on your phone. Conversations that were unread before you installed this
should still be unread, and your phone should still notify you normally. If either is not
true, stop the sync agent and open an issue.

## Uninstall

```bash
launchctl bootout gui/$(id -u)/sh.wa-inbox.run
launchctl bootout gui/$(id -u)/sh.wa-inbox.sync
rm ~/Library/LaunchAgents/sh.wa-inbox.*.plist
wacli auth logout                       # unlinks the device from WhatsApp
security delete-generic-password -s wa-inbox
rm -rf ~/.config/wa-inbox ~/.local/share/wa-inbox ~/.wacli ~/.local/bin/wa-inbox
```

Then remove the app's access at <https://myaccount.google.com/permissions>.
