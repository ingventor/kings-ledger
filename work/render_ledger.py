"""Render the private, fixed-page Paper Pro calendar from a local Outlook snapshot."""

import calendar
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab import rl_config
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from render_month import H, W, by_day, parse_utc


ROOT = Path(__file__).resolve().parent.parent
def rolling_months():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    first = max(date(2026, 10, 1), today.replace(day=1))
    months = []
    for offset in range(15):
        absolute = first.year * 12 + first.month - 1 + offset
        months.append((absolute // 12, absolute % 12 + 1))
    return months


MONTHS = rolling_months()
MONTH_KEYS = [f"{year}-{month:02d}" for year, month in MONTHS]
PAPER = HexColor("#FBF8F2")
INK = HexColor("#282B30")
RULE = HexColor("#B9B4AD")
SIDE = HexColor("#F0EBE4")
ACCENT = {
    1: "#506882", 2: "#70637E", 3: "#527565", 4: "#A66064",
    5: "#5B7D55", 6: "#A07137", 7: "#39788B", 8: "#6C7844",
    9: "#9B613F", 10: "#A4491B", 11: "#713645", 12: "#286274",
}
ART = {
    1: "winter-scene.png", 2: "winter-scene.png", 3: "spring-scene.png",
    4: "spring-scene.png", 5: "spring-scene.png", 6: "summer-scene.png",
    7: "summer-scene.png", 8: "summer-scene.png", 9: "september-scene.png",
    10: "october-scene.png", 11: "november-paint.png", 12: "december-paint.png",
}
EVENT_INK = HexColor("#A85E32")
EVENT_PALE = HexColor("#F8EBDF")
CALENDAR_COLORS = {
    "✏️": ("#A67820", "#FBF1D4"),
    "📕": ("#A33F45", "#F7E7E7"),
    "🍏": ("#3F7454", "#E5F0E7"),
    "🌊": ("#356E95", "#E5F0F7"),
    "🦾": ("#65717A", "#EAEDF0"),
    "🧫": ("#76549B", "#F0EBF7"),
}


def setup_fonts():
    base = "/System/Library/Fonts/Supplemental"
    if Path(f"{base}/Georgia.ttf").exists():
        paths = {
            "LedgerSerif": f"{base}/Georgia.ttf",
            "LedgerSerifBold": f"{base}/Georgia Bold.ttf",
            "LedgerSans": f"{base}/Trebuchet MS.ttf",
            "LedgerSansBold": f"{base}/Trebuchet MS Bold.ttf",
        }
    else:
        base = "/usr/share/fonts/truetype/dejavu"
        paths = {
            "LedgerSerif": f"{base}/DejaVuSerif.ttf",
            "LedgerSerifBold": f"{base}/DejaVuSerif-Bold.ttf",
            "LedgerSans": f"{base}/DejaVuSans.ttf",
            "LedgerSansBold": f"{base}/DejaVuSans-Bold.ttf",
        }
    for name, path in paths.items():
        pdfmetrics.registerFont(TTFont(name, path))


def tidy(value):
    return (value or "").replace("\u2014", "-").replace("\u2013", "-").replace("\u2011", "-")


def title(event):
    value = tidy(event["title"])
    return re.sub(r"\bKata(s)?\b", "Khadas", value, flags=re.I)


def location(event):
    value = tidy(event.get("location", "")).strip()
    if value.startswith(("http://", "https://")):
        return "Online"
    street = re.search(r"\b\d+\s+((?:[NSEW]\s+)?(?:[\w.'-]+\s+){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Place|Pl|Court|Ct|Circle|Cir|Parkway|Pkwy))\b", value, re.I)
    if street:
        return street.group(1)
    return re.split(r"[,;]|\b(?:apartment|apt|suite|unit)\b", value, maxsplit=1, flags=re.I)[0].strip()


def event_colors(event):
    name = event.get("calendar_name", "")
    for prefix, colors in CALENDAR_COLORS.items():
        if name.startswith(prefix):
            return tuple(map(HexColor, colors))
    if name and name != "Calendar":
        return EVENT_INK, EVENT_PALE
    label = title(event).lower()
    if any(word in label for word in ("teach", "grade papers", "lesson", "classroom")):
        return tuple(map(HexColor, CALENDAR_COLORS["🍏"]))
    if any(word in label for word in ("pen invention", "penxil", "pnxyl", "typewriter")):
        return tuple(map(HexColor, CALENDAR_COLORS["✏️"]))
    if any(word in label for word in ("khadas", "flow and focus", "client work")):
        return tuple(map(HexColor, CALENDAR_COLORS["🌊"]))
    if any(word in label for word in ("writing time", "story focus", "book", "drawing", "deep creative")):
        return tuple(map(HexColor, CALENDAR_COLORS["📕"]))
    if any(word in label for word in ("pull-ups", "push-ups", "exercise", "fitness", "aerial silks", "therapy")):
        return tuple(map(HexColor, CALENDAR_COLORS["🦾"]))
    if any(word in label for word in ("birthday", "meet up", "dinner with", "lunch with", "catch up", "visit friend")):
        return tuple(map(HexColor, CALENDAR_COLORS["🧫"]))
    return EVENT_INK, EVENT_PALE


def clock(moment, short=False):
    value = moment.strftime("%I:%M%p").lstrip("0")
    return value.lower().replace("am", "a").replace("pm", "p") if short else value[:-2] + " " + value[-2:]


def page_shell(c, year, month, subtitle):
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(SIDE)
    c.rect(0, 0, 126, H, fill=1, stroke=0)
    accent = HexColor(ACCENT[month])
    c.saveState()
    c.setFillColor(accent)
    c.setFillAlpha(.14)
    c.rect(126, H - 289, W - 126, 289, fill=1, stroke=0)
    c.restoreState()
    c.setFillColor(accent)
    c.rect(126, H - 20, W - 126, 20, fill=1, stroke=0)
    index = MONTHS.index((year, month))
    first = max(0, min(index - 1, len(MONTHS) - 3))
    for row, (y, m) in enumerate(MONTHS[first:first + 3]):
        top = H - 333 - row * 118
        active = (y, m) == (year, month)
        c.setStrokeColor(accent if active else RULE)
        c.setLineWidth(5 if active else 1)
        c.line(17, top, 109, top)
        c.setFillColor(accent if active else INK)
        c.setFont("LedgerSansBold" if active else "LedgerSans", 23)
        c.drawString(18, top - 39, calendar.month_abbr[m].upper())
        c.setFont("LedgerSans", 17)
        c.drawString(18, top - 67, str(y))
        c.linkRect("Open month", f"m-{y}-{m:02d}", (12, top - 94, 112, top + 10), relative=0)
    c.setFillColor(accent)
    c.setFont("LedgerSansBold", 22)
    c.drawString(164, H - 65, "K. ING'S LEDGER")
    c.setFillColor(INK)
    c.setFont("LedgerSerifBold", 62)
    c.drawString(161, H - 135, f"{calendar.month_name[month]} {year}")
    c.setFont("LedgerSans", 23)
    c.drawString(164, H - 183, subtitle)
    c.drawImage(str(ROOT / "assets" / ART[month]), W - 680, H - 278,
                width=625, height=260, preserveAspectRatio=True, mask="auto")
    c.setStrokeColor(RULE)
    c.setLineWidth(1.6)
    c.line(152, H - 289, W - 52, H - 289)


def month_page(c, year, month, days):
    c.bookmarkPage(f"m-{year}-{month:02d}")
    page_shell(c, year, month, "Swipe months. Tap a date for the complete month list.")
    left, right, top, bottom = 152, W - 48, H - 356, 182
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    cw, ch = (right - left) / 7, (top - bottom) / len(weeks)
    accent = HexColor(ACCENT[month])
    for column, label in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")):
        c.setFillColor(accent if column in (0, 6) else INK)
        c.setFont("LedgerSansBold", 21)
        c.drawCentredString(left + (column + .5) * cw, top + 21, label)
    for row, week in enumerate(weeks):
        for column, day in enumerate(week):
            x, y = left + column * cw, top - (row + 1) * ch
            c.setStrokeColor(RULE)
            c.setLineWidth(1)
            c.rect(x, y, cw, ch, fill=0, stroke=1)
            if not day:
                continue
            c.setFillColor(accent)
            c.rect(x + 9, y + ch - 44, 3, 31, fill=1, stroke=0)
            c.setFillColor(INK)
            c.setFont("LedgerSerifBold", 31)
            c.drawString(x + 19, y + ch - 39, str(day))
            entries = days[day]
            rail_top, rail_bottom = y + ch - 67, y + 36
            c.setStrokeColor(RULE)
            c.setLineWidth(.7)
            c.line(x + 15, rail_bottom, x + 15, rail_top)
            for hour in (0, 6, 12, 18, 24):
                mark = rail_top - hour * (rail_top - rail_bottom) / 24
                c.line(x + 12, mark, x + 18, mark)
            for start, event in entries:
                current = date(year, month, day)
                start_min = max(0, start.hour * 60 + start.minute) if start.date() == current else 0
                end = parse_utc(event["end"])
                end_min = min(1440, end.hour * 60 + end.minute) if end.date() == current else 1440
                mark = rail_top if event["all_day"] else rail_top - start_min * (rail_top - rail_bottom) / 1440
                bar_bottom = rail_top - end_min * (rail_top - rail_bottom) / 1440
                stripe, pale = event_colors(event)
                c.setFillColor(pale)
                c.setStrokeColor(stripe)
                c.rect(x + 10, min(mark, bar_bottom), 9,
                       8 if event["all_day"] else max(3, mark - bar_bottom), fill=1, stroke=1)
            last_bottom = rail_top + 24
            overflow = False
            for start, event in entries:
                current = date(year, month, day)
                start_min = start.hour * 60 + start.minute if start.date() == current else 0
                mark = rail_top if event["all_day"] else rail_top - start_min * (rail_top - rail_bottom) / 1440
                stamp = "ALL DAY" if event["all_day"] else clock(start, True)
                line = f"{stamp} {title(event)}"
                wrapped = simpleSplit(line, "LedgerSansBold", 16, cw - 49)
                lines = wrapped[:2]
                if len(wrapped) > 2:
                    while pdfmetrics.stringWidth(lines[-1] + "...", "LedgerSansBold", 16) > cw - 49:
                        lines[-1] = lines[-1][:-1]
                    lines[-1] += "..."
                loc = location(event)
                label_top = min(mark + 6, last_bottom - 6)
                label_bottom = label_top - len(lines) * 18 - (13 if loc else 0)
                if label_bottom < rail_bottom + 4:
                    overflow = True
                    break
                c.setStrokeColor(event_colors(event)[0])
                c.line(x + 19, mark, x + 29, label_top - 4)
                c.setFillColor(event_colors(event)[0])
                c.setFont("LedgerSansBold", 16)
                for offset, text_line in enumerate(lines):
                    c.drawString(x + 33, label_top - offset * 18, text_line)
                if loc:
                    short = loc
                    while pdfmetrics.stringWidth(short, "LedgerSans", 10) > cw - 50 and len(short) > 4:
                        short = short[:-2]
                    if short != loc:
                        short += "..."
                    c.setFillColor(HexColor("#656464"))
                    c.setFont("LedgerSans", 10)
                    c.drawString(x + 33, label_top - len(lines) * 18 + 2, short)
                last_bottom = label_bottom - 5
            if overflow:
                c.setFillColor(accent)
                c.setFont("LedgerSansBold", 14)
                c.drawString(x + 14, y + 10, "SEE MONTH LIST")
            c.linkRect("Open month list", f"i-{year}-{month:02d}",
                       (x, y, x + cw, y + ch), relative=0)
    c.setFillColor(INK)
    c.setFont("LedgerSans", 16)
    c.drawString(153, 111, "Each day has a 24-hour rail. Blank space shows unscheduled time; tap a date for every event.")
    c.showPage()


def month_list(c, year, month, days):
    accent = HexColor(ACCENT[month])
    column_width = (W - 152 - 48 - 36) / 2
    page_number, column, cursor = 0, 0, 0

    def start_page():
        nonlocal page_number, column, cursor
        page_number += 1
        column, cursor = 0, H - 355
        if page_number == 1:
            c.bookmarkPage(f"i-{year}-{month:02d}")
        page_shell(c, year, month, f"Complete month list  |  page {page_number}")
        c.setFillColor(accent)
        c.setFont("LedgerSansBold", 22)
        c.drawString(164, H - 244, "< MONTH GRID")
        c.linkRect("Return to month grid", f"m-{year}-{month:02d}",
                   (151, H - 270, 360, H - 210), relative=0)
        c.setFillColor(INK)
        c.setFont("LedgerSans", 14)
        c.drawRightString(W - 50, 72, f"{calendar.month_name[month]} {year}  |  {page_number}")

    def room(height):
        nonlocal column, cursor
        if cursor - height >= 125:
            return
        column += 1
        cursor = H - 355
        if column == 2:
            c.showPage()
            start_page()

    start_page()
    for day, entries in days.items():
        if not entries:
            continue
        heading = f"{calendar.month_abbr[month].upper()} {day}  {date(year, month, day):%a}".upper()
        room(45)
        x = 154 + column * (column_width + 36)
        c.setFillColor(accent)
        c.setFont("LedgerSansBold", 21)
        c.drawString(x, cursor, heading)
        cursor -= 31
        for start, event in entries:
            stamp = "ALL DAY" if event["all_day"] else ("CONT." if start.date() != date(year, month, day) else clock(start))
            lines = simpleSplit(f"{stamp}  {title(event)}", "LedgerSansBold", 20, column_width - 28)
            loc = location(event)
            location_lines = simpleSplit(loc, "LedgerSans", 13, column_width - 28) if loc else []
            height = len(lines) * 26 + len(location_lines) * 18 + 12
            old_column, old_page = column, page_number
            room(height + 34)
            if (column, page_number) != (old_column, old_page):
                x = 154 + column * (column_width + 36)
                c.setFillColor(accent)
                c.setFont("LedgerSansBold", 19)
                c.drawString(x, cursor, heading + "  CONT.")
                cursor -= 30
            x = 154 + column * (column_width + 36)
            stripe, pale = event_colors(event)
            c.setFillColor(pale)
            c.rect(x, cursor - height + 5, column_width, height + 1, fill=1, stroke=0)
            c.setFillColor(stripe)
            c.rect(x, cursor - height + 5, 5, height + 1, fill=1, stroke=0)
            c.setFillColor(stripe)
            c.setFont("LedgerSansBold", 20)
            for line in lines:
                c.drawString(x + 13, cursor - 18, line)
                cursor -= 26
            c.setFillColor(HexColor("#656464"))
            c.setFont("LedgerSans", 13)
            for line in location_lines:
                c.drawString(x + 13, cursor - 8, line)
                cursor -= 18
            cursor -= 12
        cursor -= 9
    c.showPage()


def render(data, output):
    setup_fonts()
    rl_config.useA85 = False  # Binary image streams avoid lossless ASCII85 expansion.
    if set(data) != set(MONTH_KEYS):
        raise ValueError("Expected all 15 months of source data")
    c = canvas.Canvas(str(output), pagesize=(W, H))
    c.setTitle("K. Ing's Ledger | October 2026 - December 2027")
    days_by_month = {(year, month): by_day(data[f"{year}-{month:02d}"], year, month) for year, month in MONTHS}
    for year, month in MONTHS:
        month_page(c, year, month, days_by_month[(year, month)])
    for year, month in MONTHS:
        month_list(c, year, month, days_by_month[(year, month)])
    c.save()


if __name__ == "__main__":
    assert title({"title": "Kata + Chinese"}) == "Khadas + Chinese"
    assert location({"location": "ROC City Circus, 1344 University Ave Suite 6200, Rochester"}) == "University Ave"
    assert location({"location": "2090 S Clinton Ave, Rochester"}) == "S Clinton Ave"
    assert event_colors({"calendar_name": "🧫Social"})[0] == HexColor("#76549B")
    assert event_colors({"calendar_name": "Calendar", "title": "Email sweep"})[0] == EVENT_INK
    assert event_colors({"calendar_name": "Calendar", "title": "Grade papers"})[0] == HexColor("#3F7454")
    source = json.loads((ROOT / "work" / "ledger-events.json").read_text())
    render(source, Path(sys.argv[1]))
