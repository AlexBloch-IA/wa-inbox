# Contributing

## Ground rules

1. **This tool never writes to WhatsApp.** No `send`, no `chats mark-read`, no `presence`.
   A pull request that adds one will be closed. CI fails on it too.
2. **Tune the prompt, not the code.** Most triage complaints are fixed in `prompts/` or in
   the user's own `context.md`. Reach for Python only when behaviour, not judgement, is wrong.
3. **Standard library only** in `wa_inbox/`. `pytest` and `ruff` are the only dev dependencies.

## Running the tests

```bash
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Tests use injected fakes, so they never touch WhatsApp, Google or Claude.

## Making a change

Write the failing test first. Keep modules single-purpose: `wa.py` knows only wacli,
`gtasks.py` only Google, `classify.py` only Claude, `cli.py` holds no domain judgement.

## Reporting a triage mistake

Open an issue with the message shape that was misjudged, paraphrased rather than quoted,
the decision the tool made, and the one you expected. Never paste a real contact's name,
number or message text.
