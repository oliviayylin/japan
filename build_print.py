#!/usr/bin/env python3
"""
Build a plain, unencrypted, print-friendly HTML (and PDF) version of the
itinerary for people who want a paper copy. Reads itinerary.md (same source
as build.py) and writes a standalone print HTML, then shells out to Chrome
headless to render it to PDF.

Usage:
    python3 build_print.py             # normal size, colour
    python3 build_print.py large       # larger font, colour
    python3 build_print.py bw          # normal size, black & white (for B&W printing)
    python3 build_print.py large bw    # larger font, black & white
"""
import os
import re
import subprocess
import sys

ARGS = set(sys.argv[1:])
LARGE = "large" in ARGS
BW = "bw" in ARGS

HERE = os.path.dirname(os.path.abspath(__file__))
MD_PATH = os.path.join(HERE, "itinerary.md")
SUFFIX = ("_17px" if LARGE else "") + ("_黑白" if BW else "")
OUT_HTML = os.path.join(HERE, f"行程表_列印版{SUFFIX}.html")
OUT_PDF = os.path.join(HERE, f"行程表_列印版{SUFFIX}.pdf")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# In BW mode every tag shares one neutral grey — category is already conveyed
# by the tag's own text label, so we don't lean on hue at all (hue is the
# first thing that stops working once this gets printed on a B&W printer).
TAG_STYLE = {
    "景點": ("#EAEAEA", "#1A1A1A"),
    "餐飲": ("#EAEAEA", "#1A1A1A"),
    "住宿": ("#EAEAEA", "#1A1A1A"),
    "購物": ("#EAEAEA", "#1A1A1A"),
    "交通": ("#EAEAEA", "#1A1A1A"),
    "班機": ("#EAEAEA", "#1A1A1A"),
} if BW else {
    "景點": ("#DCE6DD", "#3F6350"),
    "餐飲": ("#F6E4C5", "#8A6224"),
    "住宿": ("#DEE4EE", "#3C5578"),
    "購物": ("#E9DEEE", "#7D5490"),
    "交通": ("#CCE3DE", "#34655A"),
    "班機": ("#CCE3DE", "#34655A"),
}

COLORS = {
    "ink": "#1A1A1A", "inksoft": "#4D4D4D", "line": "#CCCCCC",
    "badgebg": "#1A1A1A", "badgefg": "#FFFFFF",
    "pillbg": "#EAEAEA", "pillfg": "#4D4D4D",
    "bpbg": "#EAEAEA", "bpplace": "#333333", "bptime": "#1A1A1A",
    "link": "#1A1A1A", "tbdborder": "#1A1A1A", "tbdtext": "#1A1A1A",
    "extraborder": "#999999", "extratitle": "#1A1A1A",
} if BW else {
    "ink": "#262421", "inksoft": "#7A7266", "line": "#E6E1D8",
    "badgebg": "#262421", "badgefg": "#FFFFFF",
    "pillbg": "#F6F5F2", "pillfg": "#7A7266",
    "bpbg": "#CCE3DE", "bpplace": "#445566", "bptime": "#34655A",
    "link": "#34655A", "tbdborder": "#5CAE9C", "tbdtext": "#34655A",
    "extraborder": "#A8C6AF", "extratitle": "#3F6350",
}

EVENT_RE = re.compile(
    r'^- (?:(?P<time>[\d:–\-]+) )?\[(?P<tag>[^\]]+)\] (?P<rest>.+)$'
)
LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
HOURS_RE = re.compile(r'\{營業\s*([^}]+)\}\s*$')
EXTRA_RE = re.compile(r'## 補充\n(.+?)(?=\n##|\Z)', re.S)
EXTRA_ROW_RE = re.compile(r'^-\s*(?:(?P<time>[\d:]+前?)\s+)?(?P<rest>.+)$')


def linkify(text):
    if text is None:
        return text
    return LINK_RE.sub(r'<a href="\2">\1</a>', text)


def parse_event_line(line):
    line = line.strip()
    hours = None
    hm = HOURS_RE.search(line)
    if hm:
        hours = hm.group(1).strip()
        line = line[:hm.start()].rstrip()

    m = EVENT_RE.match(line)
    if not m:
        raise ValueError(f"unparsable event line: {line!r}")
    time_val = m.group("time")
    tag = m.group("tag")
    rest = m.group("rest")
    tbd = False
    if "(TBD)" in rest:
        tbd = True
        rest = rest.replace("(TBD)", "").strip()
    if " — " in rest:
        title, sub = rest.split(" — ", 1)
        title, sub = title.strip(), sub.strip()
    else:
        title, sub = rest.strip(), None
    return {"time": time_val, "tag": tag, "title": title, "tbd": tbd, "sub": sub, "hours": hours}


def parse_extra_block(text):
    title = ""
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        tm = re.match(r'^標題:\s*(.+)$', line)
        if tm:
            title = tm.group(1).strip()
            continue
        rm = EXTRA_ROW_RE.match(line)
        if rm:
            rest = rm.group("rest")
            if " — " in rest:
                ttl, sub = rest.split(" — ", 1)
                ttl, sub = ttl.strip(), sub.strip()
            else:
                ttl, sub = rest.strip(), None
            rows.append({"time": rm.group("time"), "ttl": ttl, "sub": sub})
    return {"title": title, "rows": rows}


def parse_stay_line(line):
    line = line.strip()
    tbd = "(TBD)" in line
    if tbd:
        line = line.replace("(TBD)", "").strip()
    if "—" in line:
        name_part, note = line.split("—", 1)
        name_part, note = name_part.strip(), note.strip()
    else:
        name_part, note = line, None
    return {"name": name_part or None, "tbd": tbd, "note": note}


def parse_boarding_pass(line, label):
    _, route, flightno = [p.strip() for p in line.split("|")]
    left, right = route.split("→")
    m1 = re.match(r'(?P<code>\w+)\s+(?P<place>.+?)\s+(?P<time>\d{1,2}:\d{2})$', left.strip())
    m2 = re.match(r'(?P<code>\w+)\s+(?P<place>.+?)\s+(?P<time>\d{1,2}:\d{2})$', right.strip())
    return {"label": label, "flightno": flightno, "leg1": m1.groupdict(), "leg2": m2.groupdict()}


def parse_markdown(md_text):
    day_blocks = re.split(r'\n---\n', md_text)
    days = []
    trip_title, trip_meta = None, []
    for block in day_blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r'^# Day (\d+) · (\d+)/(\d+) 週(.)\n', block)
        if not m:
            tm = re.match(r'^# (.+)\n', block)
            if tm and trip_title is None:
                trip_title = tm.group(1).strip()
                trip_meta = [ln.strip("- ").strip() for ln in block.split("\n")[1:] if ln.strip().startswith("-")]
            continue
        day_num, month, day_num2, wd = m.groups()
        fields = {}
        for key in ["標題", "摘要", "標籤"]:
            fm = re.search(rf'^{key}: (.+)$', block, re.M)
            if fm:
                fields[key] = fm.group(1).strip()

        bp = None
        bp_m = re.search(r'## 航班\n(.+?)(?=\n##|\Z)', block, re.S)
        if bp_m:
            bp_line = bp_m.group(1).strip()
            label = "去程" if "去程" in bp_line else "回程"
            bp = parse_boarding_pass(bp_line, label)

        events = []
        ev_m = re.search(r'## 行程\n(.+?)(?=\n##|\Z)', block, re.S)
        if ev_m:
            for line in ev_m.group(1).strip().split("\n"):
                line = line.strip()
                if line:
                    events.append(parse_event_line(line))

        stay = None
        stay_m = re.search(r'## 住宿\n(.+?)(?=\n##|\Z)', block, re.S)
        if stay_m:
            stay = parse_stay_line(stay_m.group(1).strip())

        extras = [parse_extra_block(raw) for raw in EXTRA_RE.findall(block)]

        days.append({
            "day": day_num2, "month": month, "wd": wd,
            "ttl": fields.get("標題", ""), "sub": fields.get("摘要", ""),
            "tags": [t.strip() for t in fields.get("標籤", "").split(",") if t.strip()],
            "boarding_pass": bp, "events": events, "stay": stay, "extras": extras,
        })
    return trip_title, trip_meta, days


def render_event(ev):
    bg, fg = TAG_STYLE.get(ev["tag"], ("#F6F5F2", "#7A7266"))
    time_html = f'<span class="ev-time">{ev["time"]}</span>' if ev["time"] else '<span class="ev-time"></span>'
    tag_html = f'<span class="ev-tag" style="background:{bg};color:{fg}">{ev["tag"]}</span>'
    title_html = linkify(ev["title"])
    if ev["tbd"]:
        title_html += ' <span class="tbd">TBD</span>'
    hours_html = f'<div class="ev-hours">{ev["hours"]}</div>' if ev.get("hours") else ""
    sub_html = f'<div class="ev-sub">{linkify(ev["sub"])}</div>' if ev["sub"] else ""
    return (
        '<div class="ev">'
        f'{time_html}{tag_html}'
        f'<div class="ev-body"><div class="ev-title">{title_html}</div>{hours_html}{sub_html}</div>'
        '</div>'
    )


def render_extra_section(extra):
    rows_html = []
    for row in extra["rows"]:
        main = linkify(row["ttl"])
        if row["time"]:
            main += f' <span class="extra-time">{row["time"]}</span>'
        sub_html = f'<span class="extra-loc">{linkify(row["sub"])}</span>' if row["sub"] else ""
        rows_html.append(f'<div class="extra-row">{main}{sub_html}</div>')
    return (
        '<div class="extra">'
        f'<div class="extra-title">{extra["title"]}</div>'
        f'{"".join(rows_html)}'
        '</div>'
    )


def render_stay(stay):
    bg, fg = TAG_STYLE["住宿"]
    if stay["name"]:
        name_html = linkify(stay["name"])
        if stay["tbd"]:
            name_html += ' <span class="tbd">TBD</span>'
    else:
        name_html = "住宿未定"
    note_html = f'<div class="ev-sub">{linkify(stay["note"])}</div>' if stay["note"] else ""
    return (
        '<div class="ev">'
        f'<span class="ev-time"></span><span class="ev-tag" style="background:{bg};color:{fg}">住宿</span>'
        f'<div class="ev-body"><div class="ev-title">{name_html}</div>{note_html}</div>'
        '</div>'
    )


def render_boarding_pass(bp):
    return (
        '<div class="bp">'
        f'<div class="bp-leg"><div class="bp-code">{bp["leg1"]["code"]}</div><div class="bp-place">{bp["leg1"]["place"]}</div><div class="bp-time">{bp["leg1"]["time"]}</div></div>'
        f'<div class="bp-mid">✈<br>{bp["label"]}<br>{bp["flightno"]}</div>'
        f'<div class="bp-leg"><div class="bp-code">{bp["leg2"]["code"]}</div><div class="bp-place">{bp["leg2"]["place"]}</div><div class="bp-time">{bp["leg2"]["time"]}</div></div>'
        '</div>'
    )


def render_day(d, idx, total):
    parts = ['<section class="day">']
    parts.append('<div class="day-head">')
    parts.append(f'<div class="day-badge">Day {idx+1}</div>')
    parts.append(f'<div class="day-date">{d["month"]}/{d["day"]}（週{d["wd"]}）</div>')
    parts.append('</div>')
    parts.append(f'<h2>{d["ttl"]}</h2>')
    if d["sub"]:
        parts.append(f'<p class="day-sub">{d["sub"]}</p>')
    if d["tags"]:
        tag_pills = "".join(f'<span class="pill">{t}</span>' for t in d["tags"])
        parts.append(f'<div class="day-tags">{tag_pills}</div>')
    if d["boarding_pass"]:
        parts.append(render_boarding_pass(d["boarding_pass"]))
    parts.append('<div class="flow">')
    for ev in d["events"]:
        parts.append(render_event(ev))
    if d["stay"]:
        parts.append(render_stay(d["stay"]))
    parts.append('</div>')
    for extra in d.get("extras", []):
        parts.append(render_extra_section(extra))
    parts.append('</section>')
    return "\n".join(parts)


CSS = """
@page { size: A4; margin: 14mm 13mm; }
*{box-sizing:border-box;}
body{margin:0;font-family:"PingFang TC","Hiragino Sans","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;color:%(ink)s;font-size:%(base)spx;line-height:1.58;}
.cover{margin-bottom:7mm;}
.cover h1{font-size:%(h1)spx;margin:0 0 6px;font-weight:800;}
.cover .meta{font-size:%(base)spx;color:%(inksoft)s;}
.day{margin-bottom:7mm;break-inside:avoid-page;}
.day-head{display:flex;align-items:center;gap:11px;margin-bottom:5px;}
.day-badge{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:800;font-size:%(badge)spx;background:%(badgebg)s;color:%(badgefg)s;border-radius:7px;padding:4px 11px;}
.day-date{font-size:%(daydate)spx;color:%(inksoft)s;font-weight:700;}
.day h2{font-size:%(h2)spx;margin:2px 0 4px;font-weight:800;}
.day-sub{font-size:%(daysub)spx;color:%(inksoft)s;margin:0 0 7px;}
.day-tags{margin-bottom:8px;}
.pill{display:inline-block;font-size:%(pill)spx;font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;background:%(pillbg)s;color:%(pillfg)s;border-radius:6px;padding:2px 8px;margin-right:6px;}
.bp{display:flex;align-items:center;gap:11px;background:%(bpbg)s;border-radius:11px;padding:12px 14px;margin-bottom:9px;}
.bp-leg{flex:1;text-align:center;}
.bp-code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:800;font-size:%(bpcode)spx;}
.bp-place{font-size:%(bpplace)spx;color:%(bpplace_c)s;}
.bp-time{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:%(bptime)spx;font-weight:700;color:%(bptime_c)s;margin-top:4px;}
.bp-mid{flex:0 0 auto;text-align:center;font-size:%(bpplace)spx;color:%(bpplace_c)s;line-height:1.5;}
.flow{border-top:1px solid %(line)s;}
.ev{display:flex;align-items:flex-start;gap:9px;padding:%(evpad)spx 0;border-bottom:1px solid %(line)s;break-inside:avoid-page;}
.ev-time{flex:0 0 %(evtimew)spx;font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:%(evtime)spx;font-weight:700;color:%(inksoft)s;padding-top:2px;}
.ev-tag{flex:0 0 auto;font-size:%(evtag)spx;font-weight:700;border-radius:5px;padding:2px 7px;white-space:nowrap;}
.ev-body{flex:1;min-width:0;}
.ev-title{font-size:%(base)spx;font-weight:700;}
.ev-title a{color:%(link)s;text-decoration:underline;}
.ev-sub{font-size:%(evsub)spx;color:%(inksoft)s;margin-top:2px;}
.ev-sub a{color:%(link)s;text-decoration:underline;}
.ev-hours{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:%(evsub)spx;color:%(link)s;margin-top:2px;}
.tbd{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:%(tbd)spx;font-weight:700;color:%(tbdtext)s;border:1px dashed %(tbdborder)s;border-radius:5px;padding:0 5px;}
.extra{margin-top:9px;border:2px dashed %(extraborder)s;border-radius:11px;padding:9px 12px;break-inside:avoid-page;}
.extra-title{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:%(evtag)spx;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:%(extratitle)s;margin-bottom:6px;}
.extra-row{font-size:%(evsub)spx;padding:2px 0;}
.extra-row .extra-time{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:700;color:%(inksoft)s;margin-left:2px;}
.extra-row .extra-loc{color:%(inksoft)s;margin-left:6px;}
""" % {
    **(
        {
            "base": 17, "h1": 30, "badge": 16, "daydate": 16, "h2": 23, "daysub": 16,
            "pill": 14, "bpcode": 21, "bpplace": 13, "bptime": 17, "evpad": 8,
            "evtimew": 48, "evtime": 14, "evtag": 13, "evsub": 15, "tbd": 12,
        } if LARGE else {
            "base": 13.5, "h1": 25, "badge": 12.5, "daydate": 13, "h2": 19, "daysub": 12.5,
            "pill": 11, "bpcode": 17, "bpplace": 10.5, "bptime": 14, "evpad": 6.5,
            "evtimew": 40, "evtime": 11, "evtag": 10.5, "evsub": 12, "tbd": 10,
        }
    ),
    "ink": COLORS["ink"], "inksoft": COLORS["inksoft"], "line": COLORS["line"],
    "badgebg": COLORS["badgebg"], "badgefg": COLORS["badgefg"],
    "pillbg": COLORS["pillbg"], "pillfg": COLORS["pillfg"],
    "bpbg": COLORS["bpbg"], "bpplace_c": COLORS["bpplace"], "bptime_c": COLORS["bptime"],
    "link": COLORS["link"], "tbdborder": COLORS["tbdborder"], "tbdtext": COLORS["tbdtext"],
    "extraborder": COLORS["extraborder"], "extratitle": COLORS["extratitle"],
}


def main():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()
    trip_title, trip_meta, days = parse_markdown(md_text)

    html = ['<!doctype html><html><head><meta charset="utf-8">']
    html.append(f'<title>{trip_title}</title>')
    html.append(f'<style>{CSS}</style></head><body>')
    html.append('<div class="cover">')
    html.append(f'<h1>{trip_title}</h1>')
    for m in trip_meta:
        html.append(f'<div class="meta">{m}</div>')
    html.append('</div>')
    for idx, d in enumerate(days):
        html.append(render_day(d, idx, len(days)))
    html.append('</body></html>')

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    print(f"Wrote {OUT_HTML}")

    if not os.path.exists(CHROME):
        print("Chrome not found for PDF export; HTML written only.", file=sys.stderr)
        return

    subprocess.run([
        CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={OUT_PDF}", f"file://{OUT_HTML}",
    ], check=True, capture_output=True)
    print(f"Wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
