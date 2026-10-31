"""Render `docs/METRICS/` into one searchable HTML page, the Market Handbook (ADR-104).

The Markdown files are the source of truth; this only presents them, so it is
regenerated rather than edited: `make handbook` writes
`web/public/handbook.html` (gitignored), which the workbench serves at
`/handbook.html`. `make ui` and the daily agent batch rebuild it, so the page
follows the knowledge keeper's accepted drafts and today's tasks.

Like `render_architecture.py`, the converter handles exactly what the pages
use (headings, lists, tables, links, inline code and emphasis) and is not a
general Markdown parser.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "docs" / "METRICS"
TASKS = REPO_ROOT / "TASKS.md"
TEMPLATE = Path(__file__).resolve().parent / "handbook_template.html"
OUT = REPO_ROOT / "web" / "public" / "handbook.html"

FAMILIES = [
    ("market", "Market context"),
    ("options", "Options"),
    ("performance", "Strategy performance"),
    ("validation", "Validation and the gate"),
    ("risk", "Risk on the live book"),
    ("attribution", "Attribution"),
    ("quality", "Data quality"),
    ("fundamentals", "Company fundamentals"),
    ("macro_india", "Indian economy"),
    ("macro_global", "Global economy"),
    ("policy", "Policy and regulators"),
    ("institutions", "Institutions and flows"),
    ("events", "Market events"),
    ("structure", "Market structure"),
]
TABLE_RULE = re.compile(r"^\|[-| :]+\|$")
PAGE_LINK = re.compile(r"(?:\.\./[a-z_]+/)?([a-z0-9-]+)\.md$")


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*]+)\*(?![\w*])", r"<em>\1</em>", out)

    def link(found: re.Match[str]) -> str:
        label, href = found.group(1), found.group(2)
        page = PAGE_LINK.search(href)
        if page and not href.startswith("http"):
            return f'<a href="#{page.group(1)}" data-page="{page.group(1)}">{label}</a>'
        return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, out)
    return re.sub(
        r"(?<![\"=>])(https?://[^\s<)]+)",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        out,
    )


def render(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    in_list = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1].strip()):
            if in_list:
                out.append("</ul>")
                in_list = False
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            body = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            table = '<div class="tbl"><table><thead><tr>'
            table += "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
            for row in body:
                table += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
            out.append(table + "</tbody></table></div>")
            continue
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if line.startswith("## "):
                out.append(f"<h3>{inline(line[3:])}</h3>")
            elif line.strip() and not line.startswith("# "):
                out.append(f"<p>{inline(line)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _field(markdown: str, label: str) -> str:
    found = re.search(rf"^\*\*{re.escape(label)}\*\*\s*(.+)$", markdown, re.MULTILINE)
    return found.group(1).strip() if found else ""


def pages(source: Path = SOURCE) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for family, _ in FAMILIES:
        for path in sorted((source / family).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            name = next((ln[2:] for ln in text.splitlines() if ln.startswith("# ")), path.stem)
            body = re.sub(r"^\*Family:.*\*$", "", text, flags=re.MULTILINE)
            out.append(
                {
                    "id": path.stem,
                    "family": family,
                    "name": name,
                    "one": _field(text, "In one line:"),
                    "held": _field(text, "Do we hold it:"),
                    "html": render(body),
                    "text": re.sub(r"[`*#|]", " ", text).lower(),
                }
            )
    return out


def waiting(tasks: Path = TASKS) -> list[dict[str, str]]:
    """Rows of TASKS.md still TODO that name the operator."""
    out: list[dict[str, str]] = []
    if not tasks.exists():
        return out
    for line in tasks.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"T-\d+", cells[0]):
            status = cells[-1]
            if status.startswith("TODO") and "Operator" in status:
                out.append({"id": cells[0], "task": cells[1], "status": status})
    return out


def build(now: datetime | None = None) -> str:
    listed = pages()
    data = {
        "families": [
            {"id": f, "title": t, "count": sum(p["family"] == f for p in listed)}
            for f, t in FAMILIES
            if any(p["family"] == f for p in listed)
        ],
        "pages": listed,
        "answer": render((SOURCE / "HOW_TO_ANSWER.md").read_text(encoding="utf-8")),
        "waiting": waiting(),
        "built": (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC"),
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)


def main(argv: list[str] | None = None) -> int:
    target = Path(argv[0]) if argv else OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build(), encoding="utf-8")
    print(f"handbook: {len(pages())} pages -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
