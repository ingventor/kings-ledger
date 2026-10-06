import calendar
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas


ZONE = ZoneInfo("America/New_York")
W, H = 1620, 2160
PURPLE = HexColor("#6920D9")
TEAL = HexColor("#10A9BC")
INK = HexColor("#202020")
GRID = HexColor("#888888")


def parse_utc(value):
    return datetime.fromisoformat(value.split(".")[0].removesuffix("Z") + "+00:00").astimezone(ZONE)


def by_day(events, year, month):
    days = {day: [] for day in range(1, calendar.monthrange(year, month)[1] + 1)}
    for event in events:
        start, end = parse_utc(event["start"]), parse_utc(event["end"])
        if end <= start:
            continue
        if event["all_day"]:
            day, last = date.fromisoformat(event["start"][:10]), date.fromisoformat(event["end"][:10])
        else:
            day = start.date()
            last = end.date() + (timedelta(days=1) if end.time() != datetime.min.time() else timedelta())
        while day < last:
            if day.year == year and day.month == month:
                days[day.day].append((start, event))
            day += timedelta(days=1)
    for entries in days.values():
        entries.sort(key=lambda entry: (not entry[1]["all_day"], entry[0], entry[1]["title"]))
    return days


def label(start, event, day):
    if event["all_day"]:
        return event["title"]
    if start.date().day != day:
        return "cont. " + event["title"]
    hour = start.strftime("%I").lstrip("0")
    return f"{hour}:{start:%M}{start:%p}".lower() + "  " + event["title"]


def draw_cell(c, x, top, width, height, day, entries):
    c.setStrokeColor(GRID)
    c.setLineWidth(1.5)
    c.rect(x, top - height, width, height, fill=0, stroke=1)
    if not day:
        return
    c.setFillColor(PURPLE)
    c.roundRect(x, top - 36, 38, 36, 0, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 23)
    c.drawCentredString(x + 19, top - 27, str(day))

    available = height - 49
    for size in (14, 13, 12, 11):
        leading = size * 1.22
        wraps = [simpleSplit(label(start, event, day), "Helvetica", size, width - 18) for start, event in entries]
        required = sum(max(1, len(lines)) * leading + 6 for lines in wraps)
        if required <= available:
            break
    else:
        raise ValueError(f"day {day} has too many events for one page")
    c.setFillColor(INK)
    c.setFont("Helvetica", size)
    y = top - 51
    for lines in wraps:
        for line in lines or [""]:
            c.drawString(x + 9, y, line)
            y -= leading
        y -= 6


def render(events, year, month, output):
    c = canvas.Canvas(str(output), pagesize=(W, H))
    c.setFillColor(white)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, H - 130, W, 130, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 42)
    c.drawString(65, H - 82, f"{calendar.month_name[month]} {year}")
    c.setFillColor(TEAL)
    c.rect(W - 125, 0, 125, H - 130, fill=1, stroke=0)
    c.setFillColor(PURPLE)
    c.roundRect(W - 108, H - 225, 88, 50, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 21)
    c.drawCentredString(W - 64, H - 206, calendar.month_abbr[month].upper())

    left, right, grid_top, grid_bottom = 42, W - 144, H - 225, 270
    cell_w, cell_h = (right - left) / 7, (grid_top - grid_bottom) / 5
    for i, name in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")):
        c.setFillColor(PURPLE if i in (0, 6) else INK)
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(left + (i + .5) * cell_w, grid_top + 26, name)

    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    days = by_day(events, year, month)
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            draw_cell(c, left + col * cell_w, grid_top - row * cell_h, cell_w, cell_h, day, days.get(day, []))

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 21)
    c.drawString(42, 230, "To-Dos")
    c.drawString(760, 230, "Notes")
    c.setStrokeColor(GRID)
    for y in (195, 158, 121, 84):
        c.line(42, y, 690, y)
        c.line(760, y, W - 145, y)
    c.setFont("Helvetica", 13)
    c.setFillColor(HexColor("#666666"))
    c.drawString(42, 38, "Private preview from Outlook Calendar, generated locally")
    c.save()


if __name__ == "__main__":
    assert parse_utc("2026-10-01T13:00:00Z").hour == 9
    birthday = {"title": "Birthday", "start": "2026-10-31T00:00:00Z", "end": "2026-11-01T00:00:00Z", "all_day": True}
    assert [day for day, entries in by_day([birthday], 2026, 10).items() if entries] == [31]
    source, target = map(Path, sys.argv[1:3])
    render(json.loads(source.read_text()), 2026, 10, target)
