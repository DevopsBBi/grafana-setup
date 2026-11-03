#!/usr/bin/env python3
"""Render a template: replace @@NAME@@ with the environment variable NAME.

  @@NAME@@      the value as is
  @@NAME|url@@  the value URL-encoded (for passwords inside a connection URL)

Usage: render.py TEMPLATE OUTPUT   (variables come from inventory.env / secrets.env, loaded by scripts/lib.sh)
Fails if a variable is not defined, so a missing value never ends up silently in a config file.
"""
import os
import re
import sys
import urllib.parse

PATTERN = re.compile(r"@@([A-Z][A-Z0-9_]*)(\|url)?@@")


def render(text):
    missing = []

    def repl(m):
        name, flt = m.group(1), m.group(2)
        if name == "NOT-IMPORTED":
            return m.group(0)
        if name not in os.environ:
            missing.append(name)
            return m.group(0)
        value = os.environ[name]
        return urllib.parse.quote(value, safe="") if flt else value

    out = PATTERN.sub(repl, text)
    if missing:
        sys.exit("render.py: undefined variable(s): " + ", ".join(sorted(set(missing))))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        text = f.read()
    with open(dst, "w", encoding="utf-8") as f:
        f.write(render(text))
