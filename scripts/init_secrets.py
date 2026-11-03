#!/usr/bin/env python3
"""Render the runtime config files that hold real secrets.

The repository only ships ``config.yaml.example`` templates with ``${VAR}``
placeholders. This script fills them from ``.env`` (or the process
environment) and writes the real ``config.yaml`` next to them, which is
git-ignored. Safe to re-run: it always regenerates from the template.

    python3 scripts/init_secrets.py          # write files
    python3 scripts/init_secrets.py --check  # only report what is missing
"""

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def read_env() -> dict:
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip().strip("'\""))
    return env


def render(text: str, env: dict) -> tuple[str, list[str]]:
    missing = []

    def sub(match):
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if not value:
            if default is not None:
                return default
            missing.append(name)
            return ""
        return value

    return PLACEHOLDER.sub(sub, text), missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report only, do not write")
    args = parser.parse_args()

    env = read_env()
    templates = sorted(ROOT.glob("profiles/*/*/config.yaml.example"))
    if not templates:
        print("No config.yaml.example templates found", file=sys.stderr)
        return 1

    all_missing, written = set(), 0
    for template in templates:
        target = template.with_suffix("")  # config.yaml.example -> config.yaml
        content, missing = render(template.read_text(encoding="utf-8"), env)
        all_missing.update(missing)
        if args.check:
            continue
        if missing:
            print(f"SKIP   {target.relative_to(ROOT)} (missing env: {', '.join(sorted(set(missing)))})")
            continue
        target.write_text(content, encoding="utf-8")
        written += 1
        print(f"WROTE  {target.relative_to(ROOT)}")

    if args.check:
        if all_missing:
            print(f"Missing environment variables: {', '.join(sorted(all_missing))}", file=sys.stderr)
            return 1
        print(f"OK  all {len(templates)} templates can be rendered")
        return 0

    print(f"\n{written}/{len(templates)} config files rendered.")
    if all_missing:
        print(f"Missing: {', '.join(sorted(all_missing))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
