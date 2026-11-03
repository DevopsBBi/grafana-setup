#!/usr/bin/env python3
"""Write the keys of a small INI file (settings) into a big INI file (target), section by section.

Every other line of the target is kept as is (comments, other keys, order). A key that exists
(even commented out with ";" or "#") is replaced in place; a missing key is added at the top of
its section; a missing section is added at the end.

Usage: ini_set.py TARGET SETTINGS     (SETTINGS is already rendered, see render.py)
"""
import re
import sys


def parse_settings(text):
    sections, cur = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, [])
            continue
        k, _, v = line.partition("=")
        sections[cur].append((k.strip(), v.strip()))
    return sections


def apply(target, sections):
    for sec, pairs in sections.items():
        m = re.search(r"(?m)^\[" + re.escape(sec) + r"\][ \t]*\n", target)
        if not m:
            target = target.rstrip("\n") + f"\n\n[{sec}]\n"
            m = re.search(r"(?m)^\[" + re.escape(sec) + r"\][ \t]*\n", target)
        start = m.end()
        nxt = re.search(r"(?m)^\[", target[start:])
        end = start + nxt.start() if nxt else len(target)
        body = target[start:end]
        for k, v in pairs:
            line = f"{k} = {v}".rstrip()
            pat = re.compile(r"(?m)^[ \t]*[;#]?[ \t]*" + re.escape(k) + r"[ \t]*=.*$")
            if pat.search(body):
                body = pat.sub(lambda _m: line, body, count=1)
            else:
                body = line + "\n" + body
        target = target[:start] + body + target[end:]
    return target


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    tgt, st = sys.argv[1], sys.argv[2]
    with open(tgt, encoding="utf-8") as f:
        target = f.read()
    with open(st, encoding="utf-8") as f:
        sections = parse_settings(f.read())
    with open(tgt, "w", encoding="utf-8") as f:
        f.write(apply(target, sections))
