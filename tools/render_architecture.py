"""Render `docs/ARCHITECTURE.md` into a standalone HTML page.

The Markdown file is the source of truth; this only presents it. Kept in the
repository rather than run once by hand, because `docs/AI_BUILD_PLAN.md` is
explicit that an output which cannot be reproduced by running one script does
not count.

The converter handles exactly the constructs the document uses — headings,
fenced code, tables, lists, blockquotes, rules, and inline emphasis. It is not
a general Markdown implementation and should not be reused as one; a
half-correct general parser would be worse than an obviously specific one.
"""

from __future__ import annotations

import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "docs" / "ARCHITECTURE.md"

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*([^*]+)\*(?!\*)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline(text: str) -> str:
    """Escape first, then re-introduce only the markup we recognise."""
    out = html.escape(text)
    out = INLINE_CODE.sub(r"<code>\1</code>", out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    out = ITALIC.sub(r"<em>\1</em>", out)
    out = LINK.sub(r'<a href="\2">\1</a>', out)
    return out


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "-", cleaned).strip("-")


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


def convert(markdown: str) -> tuple[str, list[Heading]]:
    lines = markdown.split("\n")
    out: list[str] = []
    headings: list[Heading] = []
    index = 0

    def close_list(stack: list[str]) -> None:
        while stack:
            out.append(f"</{stack.pop()}>")

    list_stack: list[str] = []

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # fenced code
        if stripped.startswith("```"):
            close_list(list_stack)
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            out.append(
                '<div class="scroll"><pre><code>'
                + html.escape("\n".join(block))
                + "</code></pre></div>"
            )
            continue

        # table
        if stripped.startswith("|") and index + 1 < len(lines) and "---" in lines[index + 1]:
            close_list(list_stack)
            header = [c.strip() for c in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([c.strip() for c in lines[index].strip().strip("|").split("|")])
                index += 1
            head = "".join(f"<th>{inline(c)}</th>" for c in header)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows
            )
            out.append(
                f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>"
            )
            continue

        # heading
        match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if match:
            close_list(list_stack)
            level = len(match.group(1))
            text = match.group(2)
            anchor = slug(text)
            headings.append(Heading(level, text, anchor))
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            index += 1
            continue

        # horizontal rule
        if stripped in {"---", "***", "___"}:
            close_list(list_stack)
            out.append("<hr />")
            index += 1
            continue

        # blockquote — the document uses these for two editorial voices:
        # "a real mistake this caught" and "unverified". Both are warnings and
        # are styled as such.
        if stripped.startswith(">"):
            close_list(list_stack)
            quoted: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().lstrip(">").strip())
                index += 1
            body = inline(" ".join(q for q in quoted if q))
            out.append(f"<blockquote><p>{body}</p></blockquote>")
            continue

        # lists
        bullet = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        number = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if bullet or number:
            wanted = "ul" if bullet else "ol"
            item = (bullet or number).group(2)  # type: ignore[union-attr]
            if not list_stack:
                list_stack.append(wanted)
                out.append(f"<{wanted}>")
            elif list_stack[-1] != wanted:
                out.append(f"</{list_stack.pop()}>")
                list_stack.append(wanted)
                out.append(f"<{wanted}>")
            out.append(f"<li>{inline(item)}</li>")
            index += 1
            continue

        if not stripped:
            close_list(list_stack)
            index += 1
            continue

        # paragraph — join continuation lines so wrapping in the source does
        # not become a line break in the output.
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip():
            current = lines[index].strip()
            if (
                current.startswith(("#", ">", "|", "```"))
                or re.match(r"^\s*[-*]\s+", lines[index])
                or re.match(r"^\s*\d+\.\s+", lines[index])
                or current in {"---", "***", "___"}
            ):
                break
            paragraph.append(current)
            index += 1
        if paragraph:
            close_list(list_stack)
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")

    close_list(list_stack)
    return "\n".join(out), headings


def contents(headings: list[Heading]) -> str:
    """Only h1s — the document's seven parts plus the glossary.

    Deeper levels would produce a rail longer than the screen, which is a
    contents list nobody uses.
    """
    items = [
        f'<li><a href="#{h.anchor}">{html.escape(h.text)}</a></li>'
        for h in headings
        if h.level == 1
    ]
    return "\n".join(items)


def strip_frontmatter(markdown: str) -> str:
    """Drop the document's own title and standfirst.

    The page has a masthead carrying both, and printing them twice reads as a
    templating mistake. Removed here rather than in the Markdown, because the
    Markdown is read on its own in the repository and needs them.
    """
    lines = markdown.split("\n")
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("# "):
            start = index + 1
            break
    while start < len(lines) and (not lines[start].strip() or lines[start].strip().startswith("*")):
        start += 1
    return "\n".join(lines[start:])


def render(markdown: str) -> str:
    body, headings = convert(strip_frontmatter(markdown))
    return TEMPLATE.replace("{{CONTENTS}}", contents(headings)).replace("{{BODY}}", body)


TEMPLATE = """<title>EulerLab Architecture</title>
<style>
/* Ledger paper and ink. The palette is accounting stock — cool, faintly green —
   rather than the warm cream that has become a default; the accent is the
   petrol blue of ledger ink, and the two warning colours are deliberately not
   the accent, because this document's whole subject is separating fact from
   doubt. */
:root {
  --paper: #f6f7f4;
  --raise: #fffffe;
  --sunk: #eeefea;
  --ink: #171c1f;
  --ink-2: #545e63;
  --ink-3: #838d90;
  --rule: #dcdfd8;
  --accent: #1d5871;
  --accent-soft: #e6eef2;
  --oxide: #8a5718;
  --oxide-soft: #f6efe2;
  --red: #9a2f24;
  --red-soft: #f7ebe9;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  --sans: ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #0f1316;
    --raise: #161b1f;
    --sunk: #1b2126;
    --ink: #e9edea;
    --ink-2: #9ba6a9;
    --ink-3: #6d7679;
    --rule: #262d31;
    --accent: #7cbcd8;
    --accent-soft: #14252e;
    --oxide: #d5a45f;
    --oxide-soft: #241d12;
    --red: #e08b80;
    --red-soft: #261614;
  }
}
:root[data-theme="dark"] {
  --paper: #0f1316;
  --raise: #161b1f;
  --sunk: #1b2126;
  --ink: #e9edea;
  --ink-2: #9ba6a9;
  --ink-3: #6d7679;
  --rule: #262d31;
  --accent: #7cbcd8;
  --accent-soft: #14252e;
  --oxide: #d5a45f;
  --oxide-soft: #241d12;
  --red: #e08b80;
  --red-soft: #261614;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--serif);
  font-size: 17px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}

.wrap { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 56px; max-width: 1180px; margin: 0 auto; padding: 0 28px; }
@media (max-width: 900px) { .wrap { grid-template-columns: minmax(0, 1fr); gap: 0; } }

nav.rail { position: sticky; top: 0; align-self: start; max-height: 100vh; overflow-y: auto; padding: 44px 0 40px; }
@media (max-width: 900px) {
  nav.rail { position: static; max-height: none; border-bottom: 1px solid var(--rule); padding-bottom: 22px; }
}
nav.rail .eyebrow { font-family: var(--sans); font-size: 10.5px; letter-spacing: 0.13em; text-transform: uppercase; color: var(--ink-3); margin-bottom: 12px; }
nav.rail ol { list-style: none; margin: 0; padding: 0; counter-reset: part; display: flex; flex-direction: column; gap: 3px; }
nav.rail li { counter-increment: part; }
nav.rail a { display: block; padding: 4px 0; font-family: var(--sans); font-size: 13px; line-height: 1.35; color: var(--ink-2); text-decoration: none; border-left: 2px solid transparent; padding-left: 11px; }
nav.rail a:hover { color: var(--accent); border-left-color: var(--accent); }
nav.rail a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

main { padding: 44px 0 120px; max-width: 68ch; }

h1, h2, h3, h4 { text-wrap: balance; line-height: 1.22; margin: 0; }
h1 {
  font-size: 30px; font-weight: 600; letter-spacing: -0.015em;
  margin: 72px 0 22px; padding-bottom: 12px; border-bottom: 2px solid var(--accent);
}
main > h1:first-child { margin-top: 0; }
h2 { font-size: 22px; font-weight: 600; margin: 46px 0 14px; letter-spacing: -0.01em; }
h3 { font-size: 17.5px; font-weight: 700; margin: 32px 0 10px; }
h4 { font-size: 15px; font-weight: 700; margin: 24px 0 8px; font-family: var(--sans); }

p { margin: 0 0 17px; }
em { color: var(--ink-2); }
strong { font-weight: 700; }
a { color: var(--accent); text-underline-offset: 2px; }
hr { border: none; border-top: 1px solid var(--rule); margin: 44px 0; }

ul, ol { margin: 0 0 18px; padding-left: 24px; }
li { margin-bottom: 7px; }
li::marker { color: var(--ink-3); }

code {
  font-family: var(--mono); font-size: 0.855em;
  background: var(--sunk); padding: 1.5px 5px; border-radius: 3px;
  border: 1px solid var(--rule);
}
pre {
  font-family: var(--mono); font-size: 12.5px; line-height: 1.6;
  background: var(--sunk); border: 1px solid var(--rule);
  border-left: 3px solid var(--accent);
  border-radius: 5px; padding: 15px 17px; margin: 0;
}
pre code { background: none; border: none; padding: 0; font-size: inherit; }

.scroll { overflow-x: auto; margin: 0 0 22px; }

table { border-collapse: collapse; width: 100%; font-size: 14px; font-family: var(--sans); }
th, td { text-align: left; padding: 8px 13px 8px 0; border-bottom: 1px solid var(--rule); vertical-align: top; }
th {
  font-size: 10.5px; letter-spacing: 0.09em; text-transform: uppercase;
  color: var(--ink-3); font-weight: 600; border-bottom: 1px solid var(--ink-3);
  white-space: nowrap;
}
td { font-variant-numeric: tabular-nums; color: var(--ink-2); }
td:first-child { color: var(--ink); }
td code { font-size: 12px; }

/* The document has two recurring editorial voices, both warnings: "a real
   mistake this caught" and "unverified". They carry the argument, so they are
   set apart rather than left as ordinary quotes. */
blockquote {
  margin: 0 0 22px; padding: 14px 18px;
  background: var(--oxide-soft);
  border-left: 3px solid var(--oxide);
  border-radius: 0 5px 5px 0;
}
blockquote p { margin: 0; font-size: 15.5px; color: var(--ink); }
blockquote strong { color: var(--oxide); }

header.masthead { padding: 56px 0 0; }
header.masthead .eyebrow {
  font-family: var(--sans); font-size: 10.5px; letter-spacing: 0.15em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 14px;
}
header.masthead h1 {
  font-size: 42px; margin: 0 0 14px; border: none; padding: 0; letter-spacing: -0.025em;
}
header.masthead .standfirst { font-size: 18.5px; color: var(--ink-2); margin: 0 0 26px; }
header.masthead .facts {
  display: flex; flex-wrap: wrap; gap: 0; border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); font-family: var(--sans);
}
header.masthead .fact { padding: 13px 26px 13px 0; }
header.masthead .fact .k { font-size: 10.5px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--ink-3); }
header.masthead .fact .v { font-family: var(--mono); font-size: 16px; margin-top: 3px; font-variant-numeric: tabular-nums; }
header.masthead .fact .v.warn { color: var(--red); }

:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 2px; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>

<div class="wrap">
  <nav class="rail">
    <div class="eyebrow">Contents</div>
    <ol>
      {{CONTENTS}}
    </ol>
  </nav>
  <main>
    <header class="masthead">
      <div class="eyebrow">EulerLab &middot; internal reference</div>
      <h1>How this system works</h1>
      <p class="standfirst">
        A complete walkthrough of a quant research and execution platform for Indian
        equity markets &mdash; every component, and the mathematics underneath it.
        Written for someone who has never seen the repository.
      </p>
      <div class="facts">
        <div class="fact"><div class="k">Trials logged</div><div class="v">19</div></div>
        <div class="fact"><div class="k">Noise bar</div><div class="v">Sharpe 1.88</div></div>
        <div class="fact"><div class="k">Best result ever</div><div class="v warn">Sharpe 1.27</div></div>
        <div class="fact"><div class="k">Capital traded</div><div class="v warn">None</div></div>
      </div>
    </header>
    {{BODY}}
  </main>
</div>
"""


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "build" / "architecture.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
