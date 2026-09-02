#!/usr/bin/env python3
"""Shared daily reading tracker ("30 minutes of reading") for Goldie and Josie.

Each kid checks it off from her own app tab; the parent view (math_app) shows
per-kid per-day submissions and streaks. Own SQLite (reading.db) on the disk.
"""
import os, sqlite3
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "reading.db")
TZ = ZoneInfo("America/Denver")

KIDS = ("goldie", "josie")
KID_LABEL = {"goldie": "Goldie", "josie": "Josie"}

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS checks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kid TEXT NOT NULL,
        day TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        UNIQUE(kid, day))""")
    return con

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def today_local():
    return now_utc().astimezone(TZ).date()

def fmt_day(dstr):
    return date.fromisoformat(dstr).strftime("%a %b %-d")

def mark_today(con, kid):
    """Returns True if this was a new check-off, False if already done today."""
    cur = con.execute("INSERT OR IGNORE INTO checks(kid, day, checked_at) VALUES (?,?,?)",
                      (kid, today_local().isoformat(), iso(now_utc())))
    con.commit()
    return cur.rowcount > 0

def checked_days(con, kid):
    return {r[0] for r in con.execute("SELECT day FROM checks WHERE kid=?", (kid,)).fetchall()}

def checked_today(con, kid):
    return today_local().isoformat() in checked_days(con, kid)

def streak(con, kid):
    days = checked_days(con, kid)
    if not days:
        return 0
    n, d = 0, today_local()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n

def kid_card(base_url, kid, already, streak_n, button_label):
    """Reading check-off card for a kid's home page. Uses shared CSS classes."""
    if already:
        inner = '<div class="flash good">&#10003; 30 minutes of reading - logged for today</div>'
    else:
        inner = (f'<form method="post" action="{base_url}/reading">'
                 f'<button class="bigbtn readbtn" type="submit">{button_label}</button></form>')
    streak_line = ""
    if streak_n > 1:
        streak_line = f'<div class="muted center" style="margin-top:8px">&#128293; {streak_n}-day reading streak</div>'
    return f"""<div class="card">
  <div class="status">&#128214; Reading - 30 minutes a day</div>
  {inner}
  {streak_line}
</div>"""

def parent_section(con, days=14):
    """Parent-view section: streaks + per-kid per-day grid for recent days."""
    gdays, jdays = checked_days(con, "goldie"), checked_days(con, "josie")
    gstreak, jstreak = streak(con, "goldie"), streak(con, "josie")
    gtot, jtot = len(gdays), len(jdays)
    statgrid = f"""<div class="statgrid">
<div class="stat"><div class="n">&#128293; {gstreak}</div><div class="l">Goldie streak</div></div>
<div class="stat"><div class="n">&#128293; {jstreak}</div><div class="l">Josie streak</div></div>
<div class="stat"><div class="n">{gtot} / {jtot}</div><div class="l">total days (G / J)</div></div>
</div>"""
    rows = ""
    d = today_local()
    for _ in range(days):
        ds = d.isoformat()
        g = '<span class="yes">&#10003;</span>' if ds in gdays else '<span class="muted">-</span>'
        j = '<span class="yes">&#10003;</span>' if ds in jdays else '<span class="muted">-</span>'
        rows += f"<tr><td>{fmt_day(ds)}</td><td>{g}</td><td>{j}</td></tr>"
        d -= timedelta(days=1)
    return f"""<h2>Reading - 30 minutes a day</h2>
{statgrid}
<div class="card"><table>
<tr><th>Day</th><th>Goldie</th><th>Josie</th></tr>
{rows}
</table>
<div class="muted" style="margin-top:6px">The girls check this off themselves from their own tabs.</div></div>"""
