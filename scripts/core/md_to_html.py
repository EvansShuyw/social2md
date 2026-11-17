#!/usr/bin/env python3
"""Convert a Markdown document into a styled, self-contained HTML preview.

A lightweight, dependency-free Markdown->HTML converter tailored for the
structured notes this skill produces: headings, bold, inline code, lists,
tables, blockquotes and horizontal rules. Produces a clean Chinese-friendly
reading layout with a colored hero header.

Usage:
    python3 md_to_html.py /path/notes.md --out /path/notes.html \
        --title "视频标题" --subtitle "副标题/来源信息" --theme blue
"""

import argparse
import html
import os
import re

THEMES = {
    "blue":   ("linear-gradient(135deg,#2f6fed,#6a4bd6)", "#2f6fed", "#eaf1ff", "#16357a", "#f0f4fb", "#33415c"),
    "orange": ("linear-gradient(135deg,#e8833a,#c0444a)", "#e8833a", "#fff1e6", "#8a3a1f", "#fdf6ef", "#5a4638"),
    "green":  ("linear-gradient(135deg,#2e9e6b,#1f7a8c)", "#2e9e6b", "#e6f7f0", "#125a3c", "#eff9f4", "#2c5a48"),
}


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def md_to_body(lines):
    body = []
    i = 0
    in_quote = False
    while i < len(lines):
        ln = lines[i]
        # table
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
            header = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            data = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                data.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            for r in data:
                body.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            body.append("</tbody></table>")
            continue
        if ln.startswith("#### "):
            body.append(f"<h4>{inline(ln[5:])}</h4>")
        elif ln.startswith("### "):
            body.append(f"<h3>{inline(ln[4:])}</h3>")
        elif ln.startswith("## "):
            body.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "):
            body.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.strip() == "---":
            body.append("<hr>")
        elif ln.startswith("> "):
            if not in_quote:
                body.append("<blockquote>")
                in_quote = True
            body.append("<p>" + inline(ln[2:]) + "</p>")
        else:
            if in_quote:
                body.append("</blockquote>")
                in_quote = False
            if re.match(r"^\s*[-*] ", ln):
                body.append("<li>" + inline(re.sub(r"^\s*[-*] ", "", ln)) + "</li>")
            elif re.match(r"^\s*\d+\. ", ln):
                body.append("<li class='num'>" + inline(re.sub(r"^\s*\d+\. ", "", ln)) + "</li>")
            elif ln.strip() == "":
                body.append("")
            else:
                body.append("<p>" + inline(ln) + "</p>")
        i += 1
    if in_quote:
        body.append("</blockquote>")
    content = "\n".join(body)
    content = re.sub(r"((?:<li.*?</li>\n?)+)", lambda m: "<ul>" + m.group(1) + "</ul>", content)
    return content


def build_html(md_text, title, subtitle, theme, foot):
    grad, accent, accent_soft, heading, quote_bg, quote_text = THEMES.get(theme, THEMES["blue"])
    content = md_to_body(md_text.split("\n"))
    subtitle_html = subtitle.replace("\n", "<br>")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1f2329;--sub:#5b6472;--line:#e6e9ef;--accent:{accent};--accent-soft:{accent_soft};--quote:{quote_bg}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI","Microsoft YaHei",sans-serif;line-height:1.8;font-size:15px}}
.wrap{{max-width:920px;margin:0 auto;padding:40px 24px 80px}}
.hero{{background:{grad};color:#fff;border-radius:16px;padding:34px;margin-bottom:28px;box-shadow:0 8px 28px rgba(20,30,60,.15)}}
.hero h1{{margin:0 0 12px;font-size:27px;line-height:1.4}}
.hero .meta{{opacity:.95;font-size:13px;line-height:1.9}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:8px 30px 26px;margin-bottom:20px;box-shadow:0 2px 10px rgba(20,30,60,.04)}}
h1{{font-size:24px}} h2{{font-size:20px;margin-top:26px;padding-bottom:10px;border-bottom:2px solid var(--accent-soft);color:{heading}}}
h3{{font-size:17px;margin-top:22px;color:{heading}}} h4{{font-size:15px;margin-top:16px;color:#33415c}}
p{{margin:10px 0}} li{{margin:6px 0}} ul{{padding-left:22px}}
code{{background:#eef1f6;color:#c0392b;padding:1px 6px;border-radius:5px;font-size:13px;font-family:"SF Mono",Menlo,Consolas,monospace}}
strong{{color:#16233d}}
blockquote{{background:var(--quote);border-left:4px solid var(--accent);margin:14px 0;padding:12px 18px;border-radius:0 8px 8px 0;color:{quote_text}}}
blockquote p{{margin:4px 0}}
hr{{border:none;border-top:1px dashed var(--line);margin:26px 0}}
table{{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}}
th,td{{border:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:top}}
th{{background:var(--accent-soft);color:{heading};font-weight:600}}
tr:nth-child(even) td{{background:#fafbfe}}
.foot{{text-align:center;color:var(--sub);font-size:12px;margin-top:30px}}
@media(max-width:600px){{.wrap{{padding:18px 12px 50px}}.card{{padding:6px 16px 18px}}.hero{{padding:24px 20px}}}}
</style></head><body><div class="wrap">
<div class="hero"><h1>{html.escape(title)}</h1><div class="meta">{subtitle_html}</div></div>
<div class="card">{content}</div>
<div class="foot">{html.escape(foot)}</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", help="Input Markdown file")
    ap.add_argument("--out", help="Output HTML file (default: <md>.html)")
    ap.add_argument("--title", help="Hero title (default: first H1 or filename)")
    ap.add_argument("--subtitle", default="", help="Hero subtitle / source info (HTML line breaks with \\n)")
    ap.add_argument("--theme", default="blue", choices=list(THEMES), help="Color theme (default blue)")
    ap.add_argument("--foot", default="", help="Footer note")
    args = ap.parse_args()

    md_text = open(args.md, encoding="utf-8").read()
    title = args.title
    if not title:
        m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
        title = m.group(1).strip() if m else os.path.splitext(os.path.basename(args.md))[0]
    out = args.out or os.path.splitext(args.md)[0] + ".html"
    html_doc = build_html(md_text, title, args.subtitle, args.theme, args.foot)
    open(out, "w", encoding="utf-8").write(html_doc)
    print(f"HTML_OUT={out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
