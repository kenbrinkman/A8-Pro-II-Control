#!/usr/bin/env python3
"""Generate the public protocol reference from the private master by redaction only.

The master lives outside this repo and contains this install's identifiers plus two
vendor secrets. This script holds NO secrets itself: every literal to be removed lives
in a rules file that also sits outside the repo. That is deliberate — a redaction script
that names what it redacts is not a redaction script.

    python3 tools/redact.py                 # generate the public copy
    python3 tools/redact.py --check         # verify the public copy leaks nothing (exit 1 if it does)
    python3 tools/redact.py --diff          # show what would change, write nothing

Defaults assume the layout:

    <work folder>/
      A8-Pro-II-Protocol-Reference.md   the master        (never committed)
      redaction-rules.json              the rules         (never committed)
      A8-Pro-II-Control/                this repo
        A8-Pro-II-Protocol-Reference.md the public copy   (committed)
        tools/redact.py                 this file

Stdlib only, no network. Exit codes: 0 ok, 1 check failed, 2 bad input.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MASTER = REPO.parent / "A8-Pro-II-Protocol-Reference.md"
DEFAULT_RULES = REPO.parent / "redaction-rules.json"
DEFAULT_OUT = REPO / "A8-Pro-II-Protocol-Reference.md"

INDEX_RE = re.compile(r"\n?<!-- SECTION-INDEX -->.*?<!-- /SECTION-INDEX -->\n\n---\n", re.S)
HEADING_RE = re.compile(r"^(#{2,3}) (\d+(?:\.\d+[a-z]?)?)\.? (.*)$")


def die(msg: str, code: int = 2) -> None:
    print(f"redact: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_rules(path: Path) -> dict:
    if not path.exists():
        die(f"rules file not found: {path}\n"
            f"        It must live outside the repo — it names the strings to withhold.")
    rules = json.loads(path.read_text(encoding="utf-8"))
    for key in ("front_matter", "drop_sections", "literals", "regexes", "forbidden"):
        if key not in rules:
            die(f"rules file is missing required key: {key}")
    return rules


def strip_index(text: str) -> str:
    return INDEX_RE.sub("", text)


def swap_front_matter(text: str, replacement: str) -> str:
    """Replace everything above '### Document map' with the public front matter.

    The master's front matter names the private companion docs and declares itself the
    unredacted copy; none of that may survive. Anchoring on the document map keeps the
    rule structural rather than a brittle line count.
    """
    anchor = "\n### Document map\n"
    i = text.find(anchor)
    if i == -1:
        die("could not find the '### Document map' anchor in the master")
    return replacement.rstrip("\n") + "\n" + text[i:]


def drop_sections(text: str, numbers: list[str]) -> tuple[str, list[str]]:
    """Remove whole '### N.M' sections, up to the next heading of equal or higher level."""
    lines = text.split("\n")
    keep, dropped, skipping, depth = [], [], False, 0
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            level, number = len(m.group(1)), m.group(2)
            if skipping and level <= depth:
                skipping = False
            if not skipping and number in numbers:
                skipping, depth = True, level
                dropped.append(number)
        if not skipping:
            keep.append(line)
    missing = [n for n in numbers if n not in dropped]
    if missing:
        die(f"drop_sections named sections that are not in the master: {', '.join(missing)}")
    return "\n".join(keep), dropped


def apply_replacements(text: str, literals: list[dict], regexes: list[dict]) -> list[str]:
    """Apply literal then regex replacements. Returns a report; mutates nothing in place."""
    report = []
    for rule in literals:
        find, repl = rule["find"], rule["replace"]
        n = text.count(find)
        if n:
            text = text.replace(find, repl)
        report.append((rule.get("label", "literal"), n))
    for rule in regexes:
        pattern, repl = rule["pattern"], rule["replace"]
        text, n = re.subn(pattern, repl, text)
        report.append((rule.get("label", pattern), n))
    return text, report


def build_index(rows: list[tuple[int, str, str, int]], off: int) -> list[str]:
    out = ["<!-- SECTION-INDEX -->", "## Section index", "",
           "> 🔑 **Do not read this file whole.** Find the section here, then read only its",
           "> line range. Numbers drift — confirm with `grep -n \"^### 13.3\" <file>`.", ""]
    for depth, number, title, line in rows:
        bold = "**" if depth == 2 else ""
        indent = "" if depth == 2 else "  "
        out.append(f"{indent}- {bold}§{number} {title}{bold} — L{line + off}")
    return out + ["", "<!-- /SECTION-INDEX -->", "", "---"]


def insert_index(text: str) -> str:
    """Rebuild the section index against the redacted line numbers.

    This must run last: dropping sections moves every line below them, so an index
    copied from the master would point at the wrong places in the public copy.
    """
    lines = text.split("\n")
    rows = []
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            rows.append((len(m.group(1)), m.group(2), m.group(3).strip(), i))
    try:
        idx = lines.index("---")
    except ValueError:
        die("no '---' rule after the front matter; cannot place the section index")
    off = 1 + len(build_index(rows, 0))
    return "\n".join(lines[:idx + 1] + [""] + build_index(rows, off) + lines[idx + 1:])


def check(text: str, forbidden: list[dict]) -> list[str]:
    """Return a list of human-readable leaks. Empty list means clean."""
    leaks = []
    for rule in forbidden:
        label = rule.get("label", "?")
        if "literal" in rule:
            hits = text.count(rule["literal"])
        else:
            hits = len(re.findall(rule["pattern"], text))
        if hits:
            leaks.append(f"{label}: {hits} occurrence(s)")
    return leaks


def verify_index(text: str) -> list[str]:
    """Every index entry must point at the line its heading is actually on."""
    lines = text.split("\n")
    actual = {}
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            actual[m.group(2)] = i
    problems = []
    for entry in re.finditer(r"^\s*- \*{0,2}§([\d.]+) .*— L(\d+)$", text, re.M):
        number, claimed = entry.group(1), int(entry.group(2))
        if number in actual and actual[number] != claimed:
            problems.append(f"§{number}: index says L{claimed}, heading is at L{actual[number]}")
    return problems


def generate(master: str, rules: dict) -> tuple[str, list]:
    text = strip_index(master)
    text = swap_front_matter(text, rules["front_matter"])
    text, dropped = drop_sections(text, rules["drop_sections"])
    text, report = apply_replacements(text, rules["literals"], rules["regexes"])
    text = insert_index(text)
    if not text.endswith("\n"):
        text += "\n"
    return text, [("dropped sections", ", ".join("§" + d for d in dropped))] + report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="verify the existing public copy leaks nothing; write nothing")
    ap.add_argument("--diff", action="store_true", help="show changes without writing")
    args = ap.parse_args()

    rules = load_rules(args.rules)

    if args.check:
        if not args.out.exists():
            die(f"nothing to check: {args.out} does not exist")
        current = args.out.read_text(encoding="utf-8")
        leaks = check(current, rules["forbidden"])
        stale = verify_index(current)
        for leak in leaks:
            print(f"LEAK  {leak}")
        for problem in stale:
            print(f"INDEX {problem}")
        if leaks or stale:
            print(f"\nFAILED — {len(leaks)} leak(s), {len(stale)} bad index entry/entries.")
            return 1
        entries = len(re.findall(r"— L\d+$", current, re.M))
        print(f"clean — no withheld string survives, all {entries} index entries resolve.")
        return 0

    if not args.master.exists():
        die(f"master not found: {args.master}")

    public, report = generate(args.master.read_text(encoding="utf-8"), rules)

    leaks = check(public, rules["forbidden"])
    if leaks:
        for leak in leaks:
            print(f"LEAK  {leak}", file=sys.stderr)
        die("generated copy still contains withheld strings — refusing to write. "
            "Add a rule for each leak above.", 1)
    stale = verify_index(public)
    if stale:
        for problem in stale:
            print(f"INDEX {problem}", file=sys.stderr)
        die("generated index does not match the generated headings — refusing to write.", 1)

    if args.diff:
        old = args.out.read_text(encoding="utf-8").splitlines(keepends=True) if args.out.exists() else []
        sys.stdout.writelines(difflib.unified_diff(
            old, public.splitlines(keepends=True),
            fromfile=f"a/{args.out.name}", tofile=f"b/{args.out.name}"))
        return 0

    args.out.write_text(public, encoding="utf-8")
    width = max(len(str(label)) for label, _ in report)
    for label, count in report:
        print(f"  {str(label):<{width}}  {count}")
    print(f"\nwrote {args.out} ({len(public):,} bytes, {public.count(chr(10)) + 1} lines) — clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
