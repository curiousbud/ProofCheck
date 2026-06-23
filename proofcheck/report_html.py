"""Standalone HTML report generated from a :class:`RunResult`.

Self-contained (inline CSS, no CDNs, offline). Status colors match the web UI and
the xlsx report: green EXACT, amber FUZZY, red MISSING, grey SKIPPED.
"""

from __future__ import annotations

import html

from .models import RunResult, Status

_STATUS_CLASS = {
    Status.EXACT: "exact",
    Status.FUZZY: "fuzzy",
    Status.MISSING: "missing",
    Status.SKIPPED: "skipped",
}

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }
h1 { margin-bottom: .25rem; } .meta { color: #666; font-size: .85rem; margin-bottom: 1.5rem; }
.cards { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: .75rem 1rem; min-width: 90px; }
.card .n { font-size: 1.6rem; font-weight: 700; } .card .l { font-size: .75rem; color: #666; text-transform: uppercase; }
.warn { background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: .75rem 1rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; font-size: .9rem; }
th, td { border: 1px solid #e3e3e3; padding: .4rem .6rem; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
.badge { font-weight: 700; font-size: .75rem; padding: .1rem .45rem; border-radius: 4px; color: #fff; }
.exact { background: #2e7d32; } .fuzzy { background: #f59e0b; } .missing { background: #c62828; }
.skipped { background: #9e9e9e; }
del { background: #ffd7d5; text-decoration: line-through; } ins { background: #d7f5dd; text-decoration: none; }
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
        else:  # replace (reserved) — render both sides defensively
            out.append(f"<del>{t}</del>")
    return "".join(out)


def render(result: RunResult) -> str:
    """Return the full HTML document as a string."""
    s = result.summary
    e = html.escape
    cards = [
        ("Total", s.total), ("Exact", s.exact), ("Fuzzy", s.fuzzy),
        ("Missing", s.missing), ("Skipped", s.skipped),
        ("Pass rate", f"{s.pass_rate * 100:.1f}%"),
    ]
    parts: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>ProofCheck report</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>ProofCheck report</h1>",
        (f"<div class='meta'>Excel: <b>{e(result.meta.excel)}</b> &nbsp; "
         f"PDF: <b>{e(result.meta.pdf)}</b> &nbsp; "
         f"Threshold: {result.meta.fuzzy_threshold} &nbsp; "
         f"{e(result.meta.timestamp)}</div>"),
        "<div class='cards'>",
    ]
    for label, value in cards:
        parts.append(f"<div class='card'><div class='n'>{value}</div><div class='l'>{label}</div></div>")
    parts.append("</div>")

    if result.warnings:
        parts.append("<div class='warn'><b>Warnings</b><ul>")
        parts.extend(f"<li>{e(w)}</li>" for w in result.warnings)
        parts.append("</ul></div>")

    for col in result.columns:
        parts.append(f"<h2>{e(col.name)}</h2>")
        parts.append("<table><thead><tr><th>Row</th><th>Status</th><th>Expected</th>"
                     "<th>Best match / diff</th><th>Page</th><th>Score</th></tr></thead><tbody>")
        for r in col.results:
            cls = _STATUS_CLASS[r.status]
            diff_cell = _diff_html(r.diff) if r.diff else e(r.best_match or "")
            page = "" if r.page is None else r.page
            parts.append(
                f"<tr><td>{r.row}</td>"
                f"<td><span class='badge {cls}'>{r.status.value}</span></td>"
                f"<td>{e(r.expected)}</td><td>{diff_cell}</td>"
                f"<td>{page}</td><td>{r.score}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "".join(parts)


def write(result: RunResult, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(result))
