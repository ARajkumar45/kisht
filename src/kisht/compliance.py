"""Regulation-to-code traceability: for each recovery-conduct rule, where Kisht enforces it.

compliance/*.yaml holds one row per rule: the paragraph, what it requires (paraphrased), how
Kisht enforces it, the guard function, the tests that prove it and the block codes it
produces. This module loads the file, checks that everything a row points at really exists
(run by the tests, so the table cannot drift from the code), renders docs/COMPLIANCE.md and
counts how often each rule actually stopped something.
"""
from __future__ import annotations

import importlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

STATUS_WORDS = {"enforced": "Enforced", "partly": "Partly", "gap": "Not built",
                "not_applicable": "Not applicable"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    title: str
    number: str
    issued: date
    effective: date
    url: str
    note: str = ""


class Rule(_Strict):
    id: str
    source: str
    para: str
    requires: str
    kind: Literal["rbi", "kisht"]
    status: Literal["enforced", "partly", "gap", "not_applicable"]
    how: str
    also: list[str] = []
    gap: str = ""
    guard: list[str] = []          # "package.module:Class.method"
    config: str = ""
    codes: list[str] = []          # GuardRefused codes / reply-check codes this rule produces
    tests: list[str] = []          # "tests/file.py::test_name"


class Rulebook(_Strict):
    sources: dict[str, Source]
    rules: list[Rule]


def load(path: str | Path = "compliance/rbi-recovery-2027.yaml") -> Rulebook:
    with open(path, encoding="utf-8") as f:
        return Rulebook.model_validate(yaml.safe_load(f))


def _resolves(ref: str) -> bool:
    module, _, attr = ref.partition(":")
    try:
        obj: Any = importlib.import_module(module)
        for part in attr.split("."):
            obj = getattr(obj, part)
    except (ImportError, AttributeError):
        return False
    return True


def problems(book: Rulebook, root: str | Path = ".") -> list[str]:
    """Everything that would make the table untrue. Empty means it can be trusted."""
    root = Path(root)
    out: list[str] = []
    source_text = "\n".join(p.read_text(encoding="utf-8")
                            for p in (root / "src" / "kisht").rglob("*.py")
                            if p.name != "compliance.py")
    seen: set[str] = set()
    for r in book.rules:
        if r.id in seen:
            out.append(f"{r.id}: duplicate id")
        seen.add(r.id)
        if r.source not in book.sources:
            out.append(f"{r.id}: unknown source {r.source!r}")
        for ref in r.guard:
            if not _resolves(ref):
                out.append(f"{r.id}: guard {ref} does not exist")
        for t in r.tests:
            file, _, name = t.partition("::")
            path = root / file
            if not path.exists() or not re.search(rf"^def {re.escape(name)}\(", path.read_text(),
                                                  re.MULTILINE):
                out.append(f"{r.id}: test {t} does not exist")
        for code in r.codes:
            if f'"{code}"' not in source_text:
                out.append(f"{r.id}: block code {code!r} is not produced anywhere in src/kisht")
        if r.status in ("enforced", "partly") and not (r.guard and r.tests):
            out.append(f"{r.id}: marked {r.status} but has no guard or no test")
        if r.status == "partly" and not r.gap:
            out.append(f"{r.id}: marked partly but does not say what is missing")
        if r.status in ("gap", "not_applicable") and (r.guard or r.tests or r.codes):
            out.append(f"{r.id}: marked {r.status} but points at code")
    return out


def blocked_counts(audit_dir: str | Path, insights: Any = None) -> Counter:
    """How often each block code fired: guard refusals from the audit files (these include
    contacts refused before a conversation existed) plus replies replaced by the checks."""
    counts: Counter = Counter()
    for path in sorted(Path(audit_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if '"denied"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                code = str(entry.get("detail", "")).split(":")[0].strip()
                if entry.get("action") == "reply_blocked":
                    continue                 # counted below, from the turn it happened in
                if entry.get("outcome") == "denied" and re.fullmatch(r"[a-z_]+", code):
                    counts[code] += 1
    if insights is not None:
        for row in insights.db.execute("SELECT replaced FROM turns WHERE replaced != '[]'"):
            counts.update(json.loads(row["replaced"]))
    return counts


def summary(book: Rulebook) -> dict[str, int]:
    return dict(Counter(r.status for r in book.rules if r.kind == "rbi"))


def as_dict(book: Rulebook, counts: Counter | None = None) -> dict[str, Any]:
    rules = []
    for r in book.rules:
        d = r.model_dump()
        d["blocked"] = sum((counts or {}).get(c, 0) for c in r.codes)
        rules.append(d)
    return {"sources": {k: v.model_dump(mode="json") for k, v in book.sources.items()},
            "rules": rules, "summary": summary(book)}


def render_markdown(book: Rulebook) -> str:
    s = summary(book)
    main = book.sources[book.rules[0].source]
    lines = [
        "# Where each recovery rule is enforced",
        "",
        ("<!-- Generated from compliance/rbi-recovery-2027.yaml by `kisht compliance --write`. "
        "Edit the YAML, not this file. -->"),
        "",
        (f"The Reserve Bank of India's new recovery-conduct directions ({main.number}, issued "
        f"{main.issued:%-d %B %Y}) take effect on **{main.effective:%-d %B %Y}**. This page "
        "shows, rule by rule, where Kisht enforces them: the code that stops a breach and the "
        "tests that prove it. A test run fails if any row points at code or a test that does "
        "not exist."),
        "",
        (f"Of the {sum(s.values())} rule groups traced: **{s.get('enforced', 0)} enforced**, "
        f"**{s.get('partly', 0)} partly** (each says what is missing), "
        f"**{s.get('gap', 0)} not built**, {s.get('not_applicable', 0)} not applicable to a "
        "phone or chat agent."),
        "",
        ("Not legal advice. \"What it requires\" is a plain-English paraphrase; read the linked "
        "text before relying on it. Kisht is a demo: the lender is fictional and the borrowers "
        "are synthetic."),
        "",
        "## Sources",
        "",
    ]
    for key, src in book.sources.items():
        lines.append(f"- **{key}**: [{' '.join(src.title.split())}]({src.url}), {src.number}, "
                     f"issued {src.issued:%-d %B %Y}. {' '.join(src.note.split())}")
    for kind, title in (("rbi", "Rules"), ("kisht", "Kisht's own policy, beside the rules")):
        lines += ["", f"## {title}", "",
                  "| Paragraph | What it requires | Status | How Kisht enforces it | Code | Tests |",
                  "|---|---|---|---|---|---|"]
        for r in (x for x in book.rules if x.kind == kind):
            how = " ".join(r.how.split())
            if r.gap:
                how += f" **Missing:** {' '.join(r.gap.split())}"
            para = f"{r.para} ({r.source})" + (f"<br>also {', '.join(r.also)}" if r.also else "")
            code = "<br>".join(f"`{g.split(':')[1]}`" for g in r.guard) or "–"
            tests = "<br>".join(f"`{t.split('::')[1]}`" for t in r.tests) or "–"
            lines.append(f"| {para} | {' '.join(r.requires.split())} | "
                         f"{STATUS_WORDS[r.status]} | {how} | {code} | {tests} |")
    return "\n".join(lines) + "\n"
