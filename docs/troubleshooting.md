# Troubleshooting

Each entry gives the symptom, the likely cause, a command that confirms the cause,
and the fix.

Two paths are used throughout:

- Logs: `~/.local/share/wa-inbox/logs/`, one file per day, named `YYYY-MM-DD.log`.
  Thirty days are kept. Override the parent directory with `WA_INBOX_DATA_DIR`.
- Config: `~/.config/wa-inbox/config.json`. Override with `WA_INBOX_CONFIG_DIR`, or
  point at another file with `wa-inbox --config /path/to/config.json`.

A good first move for any symptom is a dry run, which decides and logs but writes
nothing:

```bash
wa-inbox --dry-run --force --since 24h
```

---

**Tasks stopped being created. The tool used to work, now nothing appears in Google
Tasks.**

Cause: the Google refresh token expired. While the OAuth consent screen is in
Testing mode, Google expires refresh tokens after seven days. Task creation stops
without any visible error.

Confirm:

```bash
ls -t ~/.local/share/wa-inbox/logs/ | head -1
grep -i "invalid_grant\|ERROR" "$(ls -t ~/.local/share/wa-inbox/logs/*.log | head -1)"
```

An `invalid_grant` in the newest log is the signature. The tool also posts a macOS
notification saying the Google authorisation expired, but notifications are easy to
miss.

Fix: re-run the setup to get a fresh token.

```bash
wa-inbox setup-google ~/Downloads/client_secret_*.json
```

That buys another seven days. To stop it happening again, publish the app to
production, then run the setup once more. See section 8 of `docs/google-setup.md`.

---

**Error 403 `access_denied` in the browser during Google authorisation.**

Cause: the Google account you picked is not registered as a test user on the OAuth
consent screen. The full message says the app has not completed Google's
verification process and can only be accessed by developer-approved testers.

Confirm: read the address shown in the error page or in the account chooser, then
open <https://console.cloud.google.com/auth/audience> and look at **Test users**.

Fix: add that exact address under Test users, then run `wa-inbox setup-google`
again. Step 5 of `docs/google-setup.md` has the detail. This is the most common
install failure. The address must match character for character; a Gmail address and
a Workspace address on the same person are two different users.

---

**`wacli` reports that the store is locked.**

Cause: the background sync service holds the store lock for the whole time it runs.
Anything else touching the same store at the same time is refused.

Confirm:

```bash
launchctl list | grep wa-inbox
```

If the sync agent is listed and running, it holds the lock.

Fix: read-only commands must be run with the `--read-only` flag, which is how
`wa-inbox` itself calls `wacli` for every read. Media downloads need one thing more:
`media download` must also be given an explicit `--output` path. With both, the
command works while the sync service runs.

```bash
wacli --read-only messages list --json --limit 5
wacli --read-only media download --chat <CHAT_JID> --id <MSG_ID> --output /tmp/out.jpg
```

Do not stop the sync service to work around this. Without `--read-only` a second
process can write to the store, which is exactly what the lock prevents.

---

**Contact names appear as phone numbers, or group names as raw `@g.us` identifiers.**

Cause: contacts and groups were never pulled from WhatsApp. `wa-inbox` falls back to
the chat JID when no name is known, so tasks get titles like
`120363...@g.us` instead of the group name.

Confirm: look at any recent line in the newest log. The second and third fields are
the chat name and the sender name. Digits or a bare JID there means the mirror has no
names.

Fix: the sync service must run with contact and group refresh enabled, that is with
the `--refresh-contacts` and `--refresh-groups` flags. Add them to the sync command
in the launchd agent, reload the agent, and let one sync pass complete. Names appear
on the next run. Messages already turned into tasks keep the old titles.

---

**The classifier returns no decision for some messages, and the run exits with
status 1.**

Cause: the batch handed to `claude -p` was too large, or the model truncated its
answer. `wa-inbox` requires exactly one decision per message and raises rather than
silently dropping a message.

Confirm:

```bash
grep "no decision for messages" ~/.local/share/wa-inbox/logs/*.log
```

The log line lists the message IDs that came back without a decision.

Fix: lower `batch_size` in `~/.config/wa-inbox/config.json`. The default is 50. Try
25, then 10 if it recurs. Smaller batches mean more `claude -p` calls and a slower
run, but every message gets a decision.

```json
{
  "batch_size": 25
}
```

Unprocessed messages are not lost: the cursor only advances on a successful run, so
they are picked up again next time.

---

**A notification says the WhatsApp session was lost and asks you to re-pair.**

Cause: WhatsApp unlinked the device. Either the Mac was offline long enough for
WhatsApp to drop the linked device, or the device was removed by hand from
**Linked devices** on the phone.

Confirm:

```bash
wacli --read-only auth status --json
```

`authenticated` is false.

Fix: pair again, then restart the sync service so it reconnects.

```bash
wacli auth
```

Scan the QR code from the phone under **Linked devices**, wait for the pairing to
complete, then stop and start the sync launchd agent. Messages received while the
device was unlinked are not recoverable; WhatsApp does not backfill them to a new
linked device.

---

**Nothing runs at all. No logs, no tasks, no errors.**

Cause: launchd user agents only run inside a logged-in user session. A Mac sitting at
the login screen, or one that rebooted and was never unlocked, runs nothing. FileVault
makes this worse, because a reboot stops at the pre-boot unlock screen.

Confirm:

```bash
launchctl list | grep wa-inbox
```

No output means the agents are not loaded in the current session. If there is output,
the first column is the PID (or `-` when not currently running) and the second is the
last exit status; a non-zero exit status there points at the logs.

Fix: log in on the Mac. For an unattended machine, enable automatic login and keep the
session unlocked, otherwise the tool is dormant between reboots. Check that the logs
resume after login:

```bash
tail -n 20 "$(ls -t ~/.local/share/wa-inbox/logs/*.log | head -1)"
```

---

**The local database keeps growing.**

Cause: the `wacli` store mirrors message history and downloaded media. It grows for
as long as it syncs; nothing prunes it by default.

Confirm:

```bash
wacli store stats
```

That reports the store size and what is in it.

Fix: cap the store with the `--max-db-size` option on the sync service, so old data is
trimmed once the cap is reached. Pick a size you are comfortable with, add the flag to
the sync command in the launchd agent, and reload the agent. Photos that `wa-inbox`
already copied into `images_dir` are outside the store and are not affected by the
cap.

---

**Voice notes are not transcribed. Tasks show `[voice note not transcribed]`.**

Cause: the whisper model file is missing, or `whisper_model` in the config points at
the wrong path. Transcription runs entirely locally and returns an empty string on any
failure, which the tool turns into that placeholder.

Confirm the configured path exists:

```bash
python3 -c "import os,json,pathlib; p=json.loads(pathlib.Path(os.path.expanduser('~/.config/wa-inbox/config.json')).read_text()).get('whisper_model'); print(p, os.path.exists(os.path.expanduser(p)) if p else 'not set, using default')"
ls -l ~/.local/share/wa-inbox/models/
```

The default is `~/.local/share/wa-inbox/models/ggml-small.bin`.

Fix: download the model file to that path, or set `whisper_model` in `config.json` to
wherever it actually is. Then check that the two binaries used for transcription are
on `PATH` and runnable:

```bash
which ffmpeg whisper-cli
```

If they live somewhere launchd cannot see, set `ffmpeg_bin` and `whisper_bin` in
`config.json` to absolute paths. Test the chain on a single file before re-running.

---

## Reporting a bug

Open an issue with the four items below. They are enough to diagnose almost
everything, and none of them contains a secret.

1. **The last 20 log lines, redacted.** Log lines contain chat names, sender names and
   the first 120 characters of message text. Replace phone numbers and message text
   before posting. This prints the tail for you to edit by hand:

   ```bash
   tail -n 20 "$(ls -t ~/.local/share/wa-inbox/logs/*.log | head -1)"
   ```

   Keep the timestamps, the log level and the error type. Those are what matter.

2. **Versions of the two external tools:**

   ```bash
   wacli --version
   claude --version
   ```

3. **Your `config.json`:**

   ```bash
   cat ~/.config/wa-inbox/config.json
   ```

   It is safe to paste as-is. There are no secrets in it by design: the Google client
   ID, client secret and refresh token all live in the macOS keychain under the
   service name `wa-inbox`. Never paste the output of
   `security find-generic-password -s wa-inbox -w`, which prints them in clear.

4. **What you expected and what happened**, plus whether the same run reproduces with:

   ```bash
   wa-inbox --dry-run --force --since 24h
   ```
