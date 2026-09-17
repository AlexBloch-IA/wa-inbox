"""Entry point: `wa-inbox [--dry-run ...]`, `wa-inbox setup-google <json>`, `wa-inbox init`."""
import sys

from . import cli, config, setup_google


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "setup-google":
        setup_google.main(argv[1:])
    elif argv and argv[0] == "init":
        path = config.write_default()
        example = config.prompts_dir() / "context.example.md"
        target = config.CONFIG_DIR / "context.md"
        if not target.exists():
            target.write_text(example.read_text())
        print(f"Wrote {path}\nWrote {target}\nEdit both, then run: wa-inbox --dry-run --since 48h --force")
    else:
        cli.main(argv)


if __name__ == "__main__":
    main()
