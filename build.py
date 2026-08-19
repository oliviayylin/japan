#!/usr/bin/env python3
"""
Build script for the Nagoya/Takayama/Kamikochi trip page.

Reads itinerary.md (plaintext content, source of truth) + template.html
(page shell: CSS, lock screen, decrypt script with __ENC_*__ / __HERO_IMG__
placeholders), encrypts the itinerary content with AES-256-GCM (PBKDF2-SHA256
key derivation, matching the browser's Web Crypto decrypt code exactly), and
writes the final self-contained HTML file.

Usage:
    python3 build.py

Requires: pip install cryptography
"""
import base64
import json
import os
import re
import sys

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = os.path.dirname(os.path.abspath(__file__))
MD_PATH = os.path.join(HERE, "itinerary.md")
TEMPLATE_PATH = os.path.join(HERE, "template.html")
OUTPUT_PATH = os.path.join(HERE, "2026名古屋上高地旅行.html")
HERO_IMG_PATH = os.path.join(HERE, "..", "ak0604202041夏の穂高岳と河童橋・８月（上高地）.webp")
ICONS_DIR = os.path.join(HERE, "..", "icons")

SECRET_PATH = os.path.join(HERE, ".secret_password")
if not os.path.exists(SECRET_PATH):
    raise SystemExit(
        f"Missing {SECRET_PATH}. This file holds the site password and is "
        f"gitignored on purpose (never commit a plaintext password). "
        f"Create it with: echo -n 'yourpassword' > {SECRET_PATH}"
    )
with open(SECRET_PATH, "r", encoding="utf-8") as f:
    PASSWORD = f.read().strip()

ITERATIONS = 250000

ICON_FILES = {
    "景點": ("icon-sight", "景點(綠)_recolored.png"),
    "餐飲": ("icon-food", "餐飲(黃)_recolored.png"),
    "住宿": ("icon-stay", "住宿(紫)_recolored.png"),
    "購物": ("icon-shop", "購物(粉)_recolored.png"),
    "交通": ("icon-move", "交通(藍)_recolored.png"),
    "班機": ("icon-flight", "班機(藍)_recolored.png"),
}


ICON_EMBED_PX = 64  # source icons are 256x256; downscale before embedding so the
                     # encrypted payload doesn't carry 47 full-res copies


def _load_icons():
    from PIL import Image
    import io

    icons = {}
    for tag, (css_class, filename) in ICON_FILES.items():
        path = os.path.join(ICONS_DIR, filename)
        img = Image.open(path).convert("RGBA")
        img = img.resize((ICON_EMBED_PX, ICON_EMBED_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        img_html = f'<img src="data:image/png;base64,{b64}" alt="" />'
        icons[tag] = (css_class, img_html)
    return icons


ICONS = _load_icons()

EVENT_RE = re.compile(
    r'^- (?:(?P<time>[\d:–\-]+) )?\[(?P<tag>[^\]]+)\] (?P<rest>.+)$'
)

LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')


def linkify(text):
    if text is None:
        return text
    return LINK_RE.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)


def parse_event_line(line):
    m = EVENT_RE.match(line.strip())
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
        title = title.strip()
        sub = sub.strip()
    else:
        title = rest.strip()
        sub = None
    return {"time": time_val, "tag": tag, "title": title, "tbd": tbd, "sub": sub}


def render_event(ev):
    icon_class, icon_svg = ICONS[ev["tag"]]
    title_html = linkify(ev["title"])
    if ev["tbd"]:
        title_html += ' <span class="tbd">TBD</span>'
    parts = [f'<div class="ev-icon {icon_class}">{icon_svg}</div>']
    right = ""
    if ev["time"]:
        right += f'<span class="ev-time">{ev["time"]}</span>'
    right += f'<span class="ev-title">{title_html}</span>'
    if ev["sub"]:
        right += f'<span class="ev-sub">{linkify(ev["sub"])}</span>'
    parts.append(f'<div class="ev-right">{right}</div>')
    return f'          <div class="ev">{"".join(parts)}</div>'


def parse_stay_line(line):
    line = line.strip()
    tbd = False
    if "(TBD)" in line:
        tbd = True
        line = line.replace("(TBD)", "").strip()
    if "—" in line:
        name_part, note = line.split("—", 1)
        name_part = name_part.strip()
        note = note.strip()
    else:
        name_part = line
        note = None
    name = name_part if name_part else None
    return {"name": name, "tbd": tbd, "note": note}


def render_stay(stay):
    icon_class, icon_svg = ICONS["住宿"]
    if stay["name"]:
        title_html = linkify(stay["name"])
        if stay["tbd"]:
            title_html += ' <span class="tbd">TBD</span>'
    else:
        # bare-unknown stay: plain placeholder label, no dashed TBD chip
        title_html = "住宿未定"
    right = f'<span class="ev-title">{title_html}</span>'
    if stay["note"]:
        right += f'<span class="ev-sub">{linkify(stay["note"])}</span>'
    return (
        f'          <div class="ev"><div class="ev-icon {icon_class}">{icon_svg}</div>'
        f'<div class="ev-right">{right}</div></div>'
    )


def parse_boarding_pass(line, label):
    # 去程 | TPE 桃園機場 T2 07:30 → NGO 名古屋中部機場 T1 11:20 | 中華航空 CI154
    _, route, flightno = [p.strip() for p in line.split("|")]
    left, right = route.split("→")
    m1 = re.match(r'(?P<code>\w+)\s+(?P<place>.+?)\s+(?P<time>\d{1,2}:\d{2})$', left.strip())
    m2 = re.match(r'(?P<code>\w+)\s+(?P<place>.+?)\s+(?P<time>\d{1,2}:\d{2})$', right.strip())
    return {
        "label": label,
        "flightno": flightno,
        "leg1": m1.groupdict(),
        "leg2": m2.groupdict(),
    }


def render_boarding_pass(bp):
    return (
        '      <div class="boarding-pass">\n'
        f'        <div class="bp-leg"><div class="code">{bp["leg1"]["code"]}</div>'
        f'<div class="place">{bp["leg1"]["place"]}</div><div class="time">{bp["leg1"]["time"]}</div></div>\n'
        f'        <div class="bp-mid"><div class="line"></div><div class="flight">{bp["label"]}</div>'
        f'<div class="flightno">{bp["flightno"]}</div></div>\n'
        f'        <div class="bp-leg"><div class="code">{bp["leg2"]["code"]}</div>'
        f'<div class="place">{bp["leg2"]["place"]}</div><div class="time">{bp["leg2"]["time"]}</div></div>\n'
        '      </div>\n\n'
    )


def parse_markdown(md_text):
    day_blocks = re.split(r'\n---\n', md_text)
    days = []
    transit_block = None
    for block in day_blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r'^# Day (\d+) · (\d+)/(\d+) 週(.)\n', block)
        if not m:
            if block.startswith("# 交通時間參考"):
                transit_block = block
            continue
        day_num, month, day_num2, wd = m.groups()
        fields = {}
        for key in ["標題", "摘要", "標籤", "備註"]:
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

        days.append({
            "id": f"day{day_num}",
            "day": day_num2,
            "month": month,
            "wd": wd,
            "ttl": fields.get("標題", ""),
            "sub": fields.get("摘要", ""),
            "tags": [t.strip() for t in fields.get("標籤", "").split(",") if t.strip()],
            "note": fields.get("備註"),
            "boarding_pass": bp,
            "events": events,
            "stay": stay,
        })
    return days, transit_block


GEO_SECTION = '''    <!-- TRANSIT -->
    <section class="page" id="transit" role="tabpanel" hidden>
      <div class="card geo-card">
        <svg viewBox="0 0 340 460" class="geo-svg" role="img" aria-label="行程地點相對位置與交通時間示意圖">
          <line x1="55" y1="55" x2="100" y2="105" class="geo-line"></line>
          <line x1="100" y1="105" x2="35" y2="160" class="geo-line"></line>
          <line x1="100" y1="105" x2="225" y2="115" class="geo-line"></line>
          <line x1="225" y1="115" x2="255" y2="180" class="geo-line"></line>
          <line x1="255" y1="180" x2="210" y2="265" class="geo-line"></line>
          <line x1="210" y1="265" x2="225" y2="300" class="geo-line"></line>
          <line x1="225" y1="300" x2="135" y2="375" class="geo-line"></line>
          <line x1="135" y1="375" x2="150" y2="430" class="geo-line"></line>
          <line x1="135" y1="375" x2="35" y2="160" class="geo-line"></line>
          <path d="M35,160 Q145,280 150,430" class="geo-line" fill="none"></path>

          <g class="geo-label"><rect x="60" y="70" width="34" height="16" rx="8"></rect><text x="77" y="81">30分</text></g>
          <g class="geo-label"><rect x="48" y="122" width="38" height="16" rx="8"></rect><text x="67" y="133">45分</text></g>
          <g class="geo-label"><rect x="140" y="100" width="46" height="16" rx="8"></rect><text x="163" y="111">1h14</text></g>
          <g class="geo-label"><rect x="222" y="138" width="34" height="16" rx="8"></rect><text x="239" y="149">50分</text></g>
          <g class="geo-label"><rect x="213" y="212" width="46" height="16" rx="8"></rect><text x="236" y="223">1h44</text></g>
          <g class="geo-label"><rect x="200" y="272" width="34" height="16" rx="8"></rect><text x="217" y="283">19分</text></g>
          <g class="geo-label"><rect x="158" y="327" width="46" height="16" rx="8"></rect><text x="181" y="338">1h15</text></g>
          <g class="geo-label"><rect x="122" y="392" width="34" height="16" rx="8"></rect><text x="139" y="403">50分</text></g>
          <g class="geo-label"><rect x="96" y="280" width="46" height="16" rx="8"></rect><text x="119" y="291">2h43</text></g>
          <g class="geo-label"><rect x="62" y="260" width="46" height="16" rx="8"></rect><text x="85" y="271">2h11</text></g>

          <g class="geo-node"><circle cx="55" cy="55" r="7"></circle><text x="55" y="40">上高地</text></g>
          <g class="geo-node"><circle cx="100" cy="105" r="7"></circle><text x="112" y="102" text-anchor="start">平湯溫泉</text></g>
          <g class="geo-node"><circle cx="35" cy="160" r="7"></circle><text x="35" y="178">高山</text></g>
          <g class="geo-node"><circle cx="225" cy="115" r="7"></circle><text x="225" y="100">松本</text></g>
          <g class="geo-node"><circle cx="255" cy="180" r="7"></circle><text x="269" y="184" text-anchor="start">諏訪</text></g>
          <g class="geo-node"><circle cx="210" cy="265" r="7"></circle><text x="196" y="262" text-anchor="end">妻籠宿</text></g>
          <g class="geo-node"><circle cx="225" cy="300" r="7"></circle><text x="239" y="304" text-anchor="start">馬籠宿</text></g>
          <g class="geo-node"><circle cx="135" cy="375" r="7"></circle><text x="121" y="379" text-anchor="end">名古屋</text></g>
          <g class="geo-node geo-node-end"><circle cx="150" cy="430" r="7"></circle><text x="150" y="448">中部機場</text></g>
        </svg>
      </div>
    </section>
'''


def render_day_section(d):
    out = [f'    <!-- DAY {d["id"][3:]} -->']
    out.append(f'    <section class="page" id="{d["id"]}" role="tabpanel" hidden>')
    out.append('      <div class="day-head">')
    out.append('        <div class="day-head-top">')
    out.append(f'          <span class="date-tag">{d["month"]}<span>/</span>{d["day"]}</span>')
    out.append(f'          <span class="wd-text">週{d["wd"]}</span>')
    out.append('        </div>')
    out.append(f'        <h2>{d["ttl"]}</h2>')
    out.append('      </div>\n')
    if d["boarding_pass"]:
        out.append(render_boarding_pass(d["boarding_pass"]))
    if d.get("note"):
        out.append('      <div class="banner">')
        out.append(f'        <div><b>此頁為補充建議</b>{d["note"].split("。", 1)[-1] if "。" in d["note"] else d["note"]}</div>')
        out.append('      </div>\n')
    out.append('      <div class="card">')
    out.append('        <div class="day-flow">')
    for ev in d["events"]:
        out.append(render_event(ev))
    if d["stay"]:
        out.append(render_stay(d["stay"]))
    out.append('        </div>')
    out.append('      </div>')
    out.append('    </section>\n')
    return "\n".join(out)


def build_main_html(days):
    parts = []
    parts.append('    <!-- OVERVIEW -->')
    parts.append('    <section class="page" id="overview" role="tabpanel">')
    parts.append('      <div class="ov-list" id="ovList"></div>')
    parts.append('    </section>\n')
    parts.append(GEO_SECTION)
    for d in days:
        parts.append(render_day_section(d))
    return "\n".join(parts)


def encrypt_payload(payload_dict):
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    key = kdf.derive(PASSWORD.encode("utf-8"))
    aesgcm = AESGCM(key)
    plaintext = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "iterations": ITERATIONS,
    }, plaintext


def verify_roundtrip(enc, expected_plaintext):
    salt = base64.b64decode(enc["salt"])
    iv = base64.b64decode(enc["iv"])
    ciphertext = base64.b64decode(enc["ciphertext"])
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=enc["iterations"])
    key = kdf.derive(PASSWORD.encode("utf-8"))
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(iv, ciphertext, None)
    assert decrypted == expected_plaintext, "round-trip mismatch!"
    return json.loads(decrypted.decode("utf-8"))


def main():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()
    days, _ = parse_markdown(md_text)
    print(f"Parsed {len(days)} days.")

    main_html = build_main_html(days)

    days_meta = [
        {"id": d["id"], "day": d["day"], "month": d["month"], "wd": d["wd"],
         "ttl": d["ttl"], "sub": d["sub"], "tags": d["tags"]}
        for d in days
    ]

    payload = {"mainHTML": main_html, "days": days_meta}
    enc, plaintext = encrypt_payload(payload)
    roundtrip = verify_roundtrip(enc, plaintext)
    assert roundtrip["mainHTML"] == main_html
    print("Encryption round-trip verified OK.")
    print(f"Payload size: {len(plaintext)} bytes, ciphertext b64: {len(enc['ciphertext'])} chars")

    with open(HERO_IMG_PATH, "rb") as f:
        hero_b64 = base64.b64encode(f.read()).decode()

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    for ph in ["__HERO_IMG__", "__ENC_SALT__", "__ENC_IV__", "__ENC_CT__", "__ENC_ITER__"]:
        if template.count(ph) < 1:
            print(f"WARNING: placeholder {ph} not found in template", file=sys.stderr)

    out = template
    out = out.replace("__HERO_IMG__", "data:image/webp;base64," + hero_b64)
    out = out.replace("__ENC_SALT__", enc["salt"])
    out = out.replace("__ENC_IV__", enc["iv"])
    out = out.replace("__ENC_CT__", enc["ciphertext"])
    out = out.replace("__ENC_ITER__", str(enc["iterations"]))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Wrote {OUTPUT_PATH} ({len(out)} bytes)")

    index_path = os.path.join(HERE, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Wrote {index_path} (for GitHub Pages)")


if __name__ == "__main__":
    main()
