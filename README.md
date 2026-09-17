# wa-inbox

Every 30 minutes, wa-inbox reads new WhatsApp messages sent to your personal number, has Claude decide which ones actually ask something of you, and creates a Google Task for each one. It never marks anything as read.

- Reads incoming text messages from direct chats.
- Transcribes voice notes locally with whisper, then classifies the text.
- Downloads photos attached to a request and puts the file path in the task notes.
- Reads group chats too, with the three preceding messages as context, so the classifier can tell whether a message is addressed to you.
- Sends your existing open task titles to the classifier so the same request does not become a second task.
- Skips newsletters and channels, and skips anything it has already processed.

## Why it does not mark your chats as read

wa-inbox reads WhatsApp through `wacli`, which pairs with your account as a WhatsApp Web linked device, and a linked device receiving a message is not the same thing as reading it. The only `wacli` command that sends a read receipt is `chats mark-read`, and nothing here calls it: every call the runner makes goes through `wacli --read-only`, and CI fails the build if a write command appears anywhere in the repo.

Two processes do hold a live connection, because they cannot do their job otherwise: `wacli auth` during setup, and the background sync daemon. The sync runs with `--presence-mode quiet`, which suppresses the available-presence signal, so WhatsApp does not treat your Mac as the active device and your phone keeps notifying you normally. The promise therefore rests on wacli's own sync behaviour; wacli 0.18 or later is what this was tested against. Check it yourself after a day: conversations you have not opened should still be unread.

## Requirements

- macOS.
- [Homebrew](https://brew.sh).
- `wacli` (WhatsApp CLI, <https://wacli.sh>), from the `openclaw/tap` tap:

```bash
brew tap openclaw/tap
brew install wacli
```

- `whisper-cpp` and `ffmpeg`, for local voice note transcription:

```bash
brew install whisper-cpp ffmpeg
```

- The Claude Code CLI, logged in to an Anthropic account: <https://claude.com/claude-code>. Classification runs through `claude -p`, so every run is billed to your own Anthropic plan.
- Python 3.11 or later.
- A Google account, for Google Tasks.

## Install

```bash
git clone https://github.com/AlexBloch-IA/wa-inbox.git
cd wa-inbox
./install.sh
```

The installer checks the dependencies, downloads the whisper model, pairs `wacli` with your WhatsApp account by QR code, walks you through the Google authorisation, and loads the two launchd services. Full detail, including what to do when a step fails, is in [`docs/install.md`](docs/install.md).

## How it works

1. `wacli` runs in the background and mirrors your WhatsApp account into a local SQLite store.
2. The runner asks `wacli` for messages received since its saved cursor (with a five minute overlap; two hours on the first run), keeps only text, voice notes and photos, and drops anything already in its state file.
3. Voice notes are converted with `ffmpeg` and transcribed by `whisper-cli` on your machine.
4. Each batch of 50 messages goes into a single `claude -p` call, with every tool removed, a temporary working directory, and a strict JSON schema: one decision per message, with `create`, a target list, a title, notes, and a reason.
5. For each decision that says create, a task is created through the Google Tasks API, in the list Claude picked or the default list. Every photo belonging to the request is downloaded first and appended to the notes, one path per line: the ones Claude named, plus any other photo from the same chat inside the time span the task already covers, since one complaint often arrives as several shots minutes apart. A photo is only ever attached to one task.
6. The message id is written to the state file before the task is created, and the cursor is advanced at the end of the run. The ordering is deliberate: if the process dies mid-write you may lose one task, and you will never get the same task twice.

Message text is treated as untrusted input. It is fenced inside `<messages>` tags and the prompt states that everything inside is data, never an instruction. The classifier subprocess runs with `--restricted --strict-mcp-config` and an explicit deny list, which is what actually removes its tools: an empty `--allowedTools` does not, it only pre-approves an empty list, and a subprocess launched that way still reaches the shell and inherits your own permission settings. It also runs in a throwaway directory, so it has nothing to read even if a tool slipped through.

## Configuration

The config file is `~/.config/wa-inbox/config.json`. Every key is optional; an unknown key is an error. Next to it, `context.md` is a free-text file where you describe yourself, your projects, and which task list each one maps to — that is what lets the classifier route a message to the right list instead of dumping everything in the default one.

| Key | Default | Meaning |
| --- | --- | --- |
| `default_list` | `"Inbox"` | Google Tasks list used when the classifier does not pick one. Must already exist, or the run fails. |
| `images_dir` | `~/Library/Mobile Documents/com~apple~CloudDocs/wa-inbox` | Where photos attached to a task are saved. Set to `""` to disable photo handling. |
| `active_hours` | `[7, 23]` | Local hours during which a run does work, `[start, end)`. Outside that window the run exits immediately. |
| `batch_size` | `50` | Messages per classifier call. |
| `model` | `"claude-sonnet-5"` | Model passed to `claude -p`. |
| `language` | `"en"` | Which built-in prompt to use, `"en"` or `"fr"`. |
| `context_file` | `~/.config/wa-inbox/context.md` | File appended to the system prompt to describe you and your projects. Ignored if missing. |
| `whisper_model` | `~/.local/share/wa-inbox/models/ggml-small.bin` | Path to the whisper model file used for transcription. |
| `whisper_language` | `"auto"` | Whisper language code, or `"auto"`. |
| `include_groups` | `true` | Read group chats as well as direct chats. Only messages that address you become tasks. |
| `wacli_bin` | `"wacli"` | Path to the `wacli` binary. |
| `claude_bin` | `"claude"` | Path to the Claude Code binary. |
| `ffmpeg_bin` | `"ffmpeg"` | Path to `ffmpeg`. |
| `whisper_bin` | `"whisper-cli"` | Path to the whisper-cpp binary. |

## Usage

See what it would do over the last two days, without creating anything:

```bash
wa-inbox --dry-run --since 48h --force
```

`--dry-run` decides and logs without creating a task, touching the state file, or saving a photo. It does still fetch and transcribe voice notes, since the transcription is what the decision is made on; that temporary audio is deleted afterwards. `--since` takes `48h` or an RFC 3339 timestamp like `2026-09-15T00:00:00Z`. `--force` ignores the active hours window.

Run one real pass now:

```bash
wa-inbox --force
```

Each run prints a one-line JSON summary and appends to a daily log. Logs live in `~/.local/share/wa-inbox/logs/`, one decision file per day, kept for 30 days. The two launchd agents also write `sync.out.log`, `sync.err.log`, `run.out.log` and `run.err.log` in the same directory; those are not rotated, so trim them if the sync daemon has been running for months:

```bash
tail -f ~/.local/share/wa-inbox/logs/$(date +%F).log
```

Two launchd services do the work: `sh.wa-inbox.sync` keeps the local WhatsApp mirror up to date, `sh.wa-inbox.run` triggers a pass every 30 minutes.

```bash
launchctl list | grep wa-inbox
launchctl kickstart -k gui/$(id -u)/sh.wa-inbox.run
launchctl kickstart -k gui/$(id -u)/sh.wa-inbox.sync
```

When something needs you — the WhatsApp session dropped, the Google authorisation expired, or three runs failed in a row — wa-inbox posts a macOS notification.

## Privacy

What stays on your machine:

- The WhatsApp message database maintained by `wacli`, including chats wa-inbox never looks at.
- Voice note audio. Transcription is done locally by whisper-cpp; no audio is uploaded anywhere.
- Photos. They are downloaded to `images_dir` and only their local path is written into the task notes. Note that the default `images_dir` is inside iCloud Drive, so with that default your photos are synced to Apple. Point it elsewhere if you do not want that.

What leaves your machine:

- To Anthropic, on every run that has new messages: the text of those messages (voice note transcripts included), the sender name, the chat name, whether it is a group, the timestamp, the preceding group messages used as context, the names of your Google Tasks lists, and the titles of your open tasks. This goes through the Claude Code CLI under your own account, with its usual data handling.
- To Google, for each task created: the title and notes written by the classifier, which usually quote or paraphrase the message, plus the local file path of any attached photo.

Nothing is sent to any other service, and wa-inbox has no server of its own.

## Warning

**wa-inbox talks to WhatsApp over an unofficial protocol, through a third-party library.** It is not affiliated with, endorsed by, or connected to WhatsApp or Meta in any way. Automating a WhatsApp account may violate WhatsApp's Terms of Service, and accounts using unofficial clients can in principle be rate-limited or banned. You use this at your own risk, and you are responsible for your account.

If that matters to you, pair it with a dedicated number rather than your personal one.

## License

MIT. See [`LICENSE`](LICENSE).
