"""Standalone, human-readable HTML report generated from a :class:`RunResult`.

Self-contained (inline CSS, no CDNs, offline). Written for non-technical readers: a plain
one-sentence overview, a "how to read this" legend, and per-row results in everyday
language ("Found", "Found with differences", "Not found", "Blank") with the exact text we
found and a highlighted difference. Status colors match the xlsx report and web UI.
"""

from __future__ import annotations

import html

from . import humanize
from .models import RunResult, Status

_STATUS_CLASS = {
    Status.EXACT: "exact",
    Status.FUZZY: "fuzzy",
    Status.MISSING: "missing",
    Status.SKIPPED: "skipped",
}

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; line-height: 1.45; }
h1 { margin-bottom: .25rem; } h2 { margin-top: 2rem; }
.meta { color: #666; font-size: .85rem; margin-bottom: 1rem; }
.lead { font-size: 1.05rem; background: #f3f7ff; border: 1px solid #cfe0ff; border-radius: 8px; padding: .9rem 1.1rem; margin: 1rem 0 1.25rem; }
.cards { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: .6rem 1rem; min-width: 110px; }
.card .n { font-size: 1.6rem; font-weight: 700; } .card .l { font-size: .75rem; color: #666; }
.legend { border: 1px solid #e3e3e3; border-radius: 8px; padding: .75rem 1rem; margin-bottom: 1.5rem; font-size: .9rem; }
.legend ul { margin: .4rem 0 0; padding-left: 1.1rem; } .legend li { margin: .15rem 0; }
.warn { background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: .75rem 1rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: .9rem; }
th, td { border: 1px solid #e3e3e3; padding: .5rem .6rem; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
.badge { display: inline-block; font-weight: 700; font-size: .8rem; padding: .15rem .5rem; border-radius: 999px; color: #fff; white-space: nowrap; }
.exact { background: #2e7d32; } .fuzzy { background: #f59e0b; } .missing { background: #c62828; }
.skipped { background: #9e9e9e; }
.detail { color: #333; } .diffline { margin-top: .35rem; font-size: .88rem; }
.diffline .lbl { color: #666; }
.src { font-size: .78rem; font-weight: 600; padding: .1rem .45rem; border-radius: 4px; white-space: nowrap; }
.src-ocr { background: #ede7f6; color: #5e35b1; } .src-text { background: #eef3f8; color: #37474f; }
.src-none { color: #999; }
del { background: #ffd7d5; text-decoration: line-through; } ins { background: #d7f5dd; text-decoration: none; }
.muted { color: #777; }
"""


def _diff_html(diff: list[tuple[str, str]]) -> str:
    out = []
    for op, text in diff:
        t = html.escape(text)
        if op == "equal":
            out.append(t)
        elif op == "delete":
            out.append(f"<del>{t}</del>")
        elif op == "insert":
            out.append(f"<ins>{t}</ins>")
        else:  # replace (reserved) — render defensively
            out.append(f"<del>{t}</del>")
    return "".join(out)


def render(result: RunResult) -> str:
    """Return the full HTML document as a string."""
    s = result.summary
    e = html.escape
    cards = [
        ("Values checked", s.total - s.skipped),
        ("Found", s.exact),
        ("Found with differences", s.fuzzy),
        ("Not found", s.missing),
        ("Blank", s.skipped),
        ("Match rate", f"{s.pass_rate * 100:.0f}%"),
    ]
    parts: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>ProofCheck results</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>ProofCheck results</h1>",
        (f"<div class='meta'>Spreadsheet: <b>{e(result.meta.excel)}</b> &nbsp;·&nbsp; "
         f"PDF: <b>{e(result.meta.pdf)}</b> &nbsp;·&nbsp; {e(result.meta.timestamp)}</div>"),
        f"<div class='lead'>{e(humanize.summary_sentence(result))}</div>",
        "<div class='cards'>",
    ]
    for label_text, value in cards:
        parts.append(f"<div class='card'><div class='n'>{value}</div><div class='l'>{e(label_text)}</div></div>")
    parts.append("</div>")

    # How-to-read legend.
    parts.append("<div class='legend'><b>How to read this report</b><ul>")
    for status in (Status.EXACT, Status.FUZZY, Status.MISSING, Status.SKIPPED):
        cls = _STATUS_CLASS[status]
        parts.append(
            f"<li><span class='badge {cls}'>{humanize.icon(status)} {e(humanize.label(status))}</span> "
            f"— {e(humanize.meaning(status))}</li>"
        )
    parts.append(
        "<li class='muted'>In the differences, <del>red struck-through</del> text is in your "
        "spreadsheet but not the PDF, and <ins>green</ins> text is in the PDF but not your "
        "spreadsheet.</li>"
    )
    parts.append(
        "<li><b>Matched&nbsp;via</b> shows where the PDF text came from: "
        "<span class='src src-text'>Text layer</span> (the PDF's real text) or "
        "<span class='src src-ocr'>OCR</span> (read from a scanned/image page).</li>"
    )
    parts.append("</ul></div>")

    if result.warnings:
        parts.append("<div class='warn'><b>Notes</b><ul>")
        parts.extend(f"<li>{e(w)}</li>" for w in result.warnings)
        parts.append("</ul></div>")

    for col in result.columns:
        parts.append(f"<h2>{e(col.name)}</h2>")
        parts.append("<table><thead><tr><th>Row</th><th>Value in your spreadsheet</th>"
                     "<th>Result</th><th>Matched&nbsp;via</th><th>Details</th></tr></thead><tbody>")
        for r in col.results:
            cls = _STATUS_CLASS[r.status]
            badge = f"<span class='badge {cls}'>{humanize.icon(r.status)} {e(humanize.label(r.status))}</span>"
            src = humanize.source_label(r.source)
            src_cell = f"<span class='src src-{'ocr' if r.source == 'OCR' else 'text' if r.source == 'text' else 'none'}'>{e(src)}</span>"
            detail = f"<span class='detail'>{e(humanize.detail(r))}</span>"
            if r.status is Status.FUZZY and r.diff:
                detail += (f"<div class='diffline'><span class='lbl'>Difference:</span> "
                           f"{_diff_html(r.diff)}</div>")
            parts.append(
                f"<tr><td>{r.row}</td><td>{e(r.expected) or '<span class=muted>(empty)</span>'}</td>"
                f"<td>{badge}</td><td>{src_cell}</td><td>{detail}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "".join(parts)


def write(result: RunResult, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(result))
