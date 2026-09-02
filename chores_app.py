#!/usr/bin/env python3
"""Family chores/tasks module. Served by app.py alongside the other kid apps.

Kristy quick-adds tasks from the unified parent dashboard: one-off tasks for a
date (default today) or recurring tasks (every day, or specific weekdays).
Each kid sees her own tasks on her own tab as one-tap check-offs; tasks reset
automatically each day. Own SQLite (chores.db) on the persistent disk.
"""
import os, sqlite3
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "chores.db")
TZ = ZoneInfo("America/Denver")

KIDS = ("kenzie", "goldie", "josie")
KID_LABEL = {"kenzie": "Kenzie", "goldie": "Goldie", "josie": "Josie"}
DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        kind TEXT NOT NULL,          -- 'once', 'daily', 'weekly'
        date TEXT,                   -- ISO day, for kind='once'
        dow TEXT,                    -- csv of weekday ints (Mon=0), for kind='weekly'
        active INTEGER NOT NULL DEFAULT 1,
        created TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS task_kids(
        task_id INTEGER NOT NULL,
        kid TEXT NOT NULL,
        UNIQUE(task_id, kid))""")
    con.execute("""CREATE TABLE IF NOT EXISTS completions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        kid TEXT NOT NULL,
        day TEXT NOT NULL,
        done_at TEXT NOT NULL,
        UNIQUE(task_id, kid, day))""")
    return con

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def today_local():
    return now_utc().astimezone(TZ).date()

def fmt_day(dstr):
    return date.fromisoformat(dstr).strftime("%a %b %-d")

def fmt_time(dts):
    return datetime.fromisoformat(dts).astimezone(TZ).strftime("%-I:%M %p")

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def tasks_for_day(con, kid, day=None):
    """A kid's tasks for one local day, with done state. Newest last (stable order)."""
    d = day or today_local().isoformat()
    wd = date.fromisoformat(d).weekday()
    rows = con.execute("""
        SELECT t.id, t.title, c.done_at FROM tasks t
        JOIN task_kids tk ON tk.task_id=t.id AND tk.kid=?
        LEFT JOIN completions c ON c.task_id=t.id AND c.kid=? AND c.day=?
        WHERE t.active=1 AND (
            (t.kind='once' AND t.date=?)
            OR t.kind='daily'
            OR (t.kind='weekly' AND (',' || t.dow || ',') LIKE '%,' || ? || ',%'))
        ORDER BY t.id""", (kid, kid, d, d, str(wd))).fetchall()
    return [{"id": r[0], "title": r[1], "done": r[2] is not None, "done_at": r[2]} for r in rows]

def remaining_count(con, kid):
    return sum(1 for t in tasks_for_day(con, kid) if not t["done"])

def toggle(con, task_id, kid):
    """Flip today's done state for one of the kid's tasks. Returns new done state, or None if not hers today."""
    today = today_local().isoformat()
    ids = {t["id"] for t in tasks_for_day(con, kid)}
    if task_id not in ids:
        return None
    row = con.execute("SELECT id FROM completions WHERE task_id=? AND kid=? AND day=?",
                      (task_id, kid, today)).fetchone()
    if row:
        con.execute("DELETE FROM completions WHERE id=?", (row[0],))
        con.commit()
        return False
    con.execute("INSERT INTO completions(task_id, kid, day, done_at) VALUES (?,?,?,?)",
                (task_id, kid, today, iso(now_utc())))
    con.commit()
    return True

def add_task(con, title, kids, kind, date_s, dows):
    cur = con.execute("INSERT INTO tasks(title, kind, date, dow, active, created) VALUES (?,?,?,?,1,?)",
                      (title, kind, date_s if kind == "once" else None,
                       ",".join(str(d) for d in dows) if kind == "weekly" else None,
                       iso(now_utc())))
    tid = cur.lastrowid
    for k in kids:
        con.execute("INSERT OR IGNORE INTO task_kids(task_id, kid) VALUES (?,?)", (tid, k))
    con.commit()
    return tid

def schedule_desc(t):
    kind, date_s, dow = t["kind"], t["date"], t["dow"]
    if kind == "daily":
        return "Every day"
    if kind == "weekly":
        days = [DOW_LABELS[int(x)] for x in (dow or "").split(",") if x != ""]
        return "Every " + ", ".join(days) if days else "Weekly"
    return f"Once - {fmt_day(date_s)}" if date_s else "Once"

# ---------- kid tab card (one-tap check-offs) ----------

_OPEN_STYLE = ("display:block;width:100%;text-align:left;padding:15px 16px;font-size:1.08rem;"
               "border:2px solid #d8dee4;border-radius:12px;background:#fff;cursor:pointer;"
               "font-family:inherit;color:inherit;")
_DONE_STYLE = ("display:block;width:100%;text-align:left;padding:15px 16px;font-size:1.08rem;"
               "border:2px solid #bfe6cc;border-radius:12px;background:#e5f9ee;color:#177a3f;"
               "cursor:pointer;font-family:inherit;")

def kid_card(con, base_url, kid):
    """Today's tasks card for a kid's home page. Empty string when nothing is assigned."""
    tasks = tasks_for_day(con, kid)
    if not tasks:
        return ""
    rows = ""
    for t in tasks:
        if t["done"]:
            rows += (f'<form method="post" action="{base_url}/chore" style="margin:0 0 8px">'
                     f'<input type="hidden" name="task_id" value="{t["id"]}">'
                     f'<button type="submit" style="{_DONE_STYLE}">'
                     f'<span style="text-decoration:line-through">&#10003; {esc(t["title"])}</span></button></form>')
        else:
            rows += (f'<form method="post" action="{base_url}/chore" style="margin:0 0 8px">'
                     f'<input type="hidden" name="task_id" value="{t["id"]}">'
                     f'<button type="submit" style="{_OPEN_STYLE}">'
                     f'&#9898;&nbsp; {esc(t["title"])}</button></form>')
    done = sum(1 for t in tasks if t["done"])
    if done == len(tasks):
        banner = ('<div style="background:#e5f9ee;color:#177a3f;border-radius:12px;padding:13px;'
                  'text-align:center;font-weight:700;margin-bottom:10px">'
                  'All tasks done today! &#127881;</div>')
    else:
        banner = ""
    return f"""<div class="card">
  <div class="status">&#129529; Today's tasks</div>
  {banner}
  {rows}
  <div class="muted center" style="margin-top:4px">{done} of {len(tasks)} done &middot; tap a task when it's finished</div>
</div>"""

# ---------- parent dashboard section ----------

_INPUT = ("width:100%;padding:13px;font-size:1rem;border:1px solid #ccc;border-radius:10px;"
          "margin-bottom:10px;font-family:inherit;")
_CHK = ("display:inline-flex;align-items:center;gap:7px;background:#f4f5f7;border-radius:10px;"
        "padding:10px 14px;margin:0 6px 8px 0;font-size:1rem;cursor:pointer;")

def _kid_checks(selected):
    return "".join(
        f'<label style="{_CHK}"><input type="checkbox" name="kid_{k}" value="1"'
        f'{" checked" if k in selected else ""} style="width:20px;height:20px"> {KID_LABEL[k]}</label>'
        for k in KIDS)

def _dow_checks(selected):
    return "".join(
        f'<label style="{_CHK};padding:8px 10px;font-size:.92rem"><input type="checkbox" name="dow_{i}" value="1"'
        f'{" checked" if i in selected else ""} style="width:18px;height:18px"> {DOW_LABELS[i]}</label>'
        for i in range(7))

def _kind_options(kind):
    opts = [("once", "Just this one day"), ("daily", "Repeats every day"),
            ("weekly", "Repeats on the days ticked below")]
    return "".join(f'<option value="{v}"{" selected" if v == kind else ""}>{lbl}</option>' for v, lbl in opts)

def add_form(bbase, today_s):
    return f"""<div class="card">
  <div class="status" style="text-align:left;font-weight:700">Add a task</div>
  <form method="post" action="{bbase}/chore_add">
    <input type="text" name="title" maxlength="120" placeholder="e.g. Clean your room, do the dishes" required style="{_INPUT}">
    <div style="margin-bottom:2px">{_kid_checks(("goldie", "josie"))}</div>
    <label style="display:block;font-size:.85rem;color:#555;margin:6px 0 4px">Date (for one-day tasks)</label>
    <input type="date" name="date" value="{today_s}" style="{_INPUT}">
    <label style="display:block;font-size:.85rem;color:#555;margin:6px 0 4px">Repeat</label>
    <select name="kind" style="{_INPUT}">{_kind_options("once")}</select>
    <div style="margin-bottom:6px">{_dow_checks(())}</div>
    <button style="display:block;width:100%;border:0;border-radius:12px;padding:15px 0;font-size:1.08rem;font-weight:600;color:#fff;background:#2f6fed;cursor:pointer;margin-top:6px" type="submit">Add task</button>
  </form>
</div>"""

def today_card(con):
    blocks = ""
    any_tasks = False
    for k in KIDS:
        tasks = tasks_for_day(con, k)
        if not tasks:
            continue
        any_tasks = True
        lines = ""
        for t in tasks:
            if t["done"]:
                lines += (f'<div style="padding:5px 0"><span class="yes">&#10003;</span> '
                          f'<span style="text-decoration:line-through;color:#777">{esc(t["title"])}</span> '
                          f'<span class="muted">{fmt_time(t["done_at"])}</span></div>')
            else:
                lines += (f'<div style="padding:5px 0"><span class="no">&#9711;</span> '
                          f'{esc(t["title"])} <span class="muted">not done yet</span></div>')
        blocks += f'<div style="margin-bottom:10px"><b>{KID_LABEL[k]}</b>{lines}</div>'
    if not any_tasks:
        blocks = '<div class="muted">No tasks for today yet - add one above.</div>'
    return f'<div class="card"><div class="status" style="text-align:left;font-weight:700">Today</div>{blocks}</div>'

def manage_card(con, bbase):
    today_s = today_local().isoformat()
    rows = con.execute("""SELECT id, title, kind, date, dow FROM tasks
                          WHERE active=1 AND (kind IN ('daily','weekly') OR date>=?)
                          ORDER BY id DESC""", (today_s,)).fetchall()
    lines = ""
    for tid, title, kind, date_s, dow in rows:
        kids = [r[0] for r in con.execute("SELECT kid FROM task_kids WHERE task_id=? ORDER BY kid", (tid,)).fetchall()]
        klbl = ", ".join(KID_LABEL.get(k, k) for k in kids) or "nobody"
        t = {"kind": kind, "date": date_s, "dow": dow}
        lines += f"""<tr>
<td>{esc(title)}</td><td class="muted">{esc(klbl)}</td><td class="muted">{schedule_desc(t)}</td>
<td style="white-space:nowrap">
  <a href="{bbase}/chore_edit/{tid}" style="font-size:.9rem">edit</a>
  <form method="post" action="{bbase}/chore_del" style="display:inline" onsubmit="return confirm('Delete this task?')">
    <input type="hidden" name="id" value="{tid}"><button class="delbtn" title="Delete">&#10005;</button>
  </form>
</td></tr>"""
    if not lines:
        lines = '<tr><td colspan="4" class="muted">No tasks yet.</td></tr>'
    return f"""<div class="card"><table>
<tr><th>Task</th><th>Who</th><th>When</th><th></th></tr>
{lines}
</table>
<div class="muted" style="margin-top:6px">Recurring tasks show up on the girls' tabs every matching day on their own. One-day tasks only appear on their date.</div></div>"""

def parent_section(con, boss_token):
    bbase = "/boss/" + boss_token
    today_s = today_local().isoformat()
    return f"""<h2 id="chores">Chores &amp; tasks</h2>
{add_form(bbase, today_s)}
{today_card(con)}
{manage_card(con, bbase)}"""

def edit_body(con, task_id, boss_token):
    bbase = "/boss/" + boss_token
    row = con.execute("SELECT id, title, kind, date, dow FROM tasks WHERE id=? AND active=1", (task_id,)).fetchone()
    if not row:
        return None
    tid, title, kind, date_s, dow = row
    kids = {r[0] for r in con.execute("SELECT kid FROM task_kids WHERE task_id=?", (tid,)).fetchall()}
    dows = {int(x) for x in (dow or "").split(",") if x != ""}
    return f"""
<h1>Edit task</h1>
<div class="sub"><a href="/parent/PARENTTOKEN_PLACEHOLDER">back to the dashboard</a></div>
<div class="card">
  <form method="post" action="{bbase}/chore_save">
    <input type="hidden" name="id" value="{tid}">
    <label style="display:block;font-size:.85rem;color:#555;margin:6px 0 4px">Task</label>
    <input type="text" name="title" maxlength="120" value="{esc(title)}" required style="{_INPUT}">
    <div style="margin-bottom:2px">{_kid_checks(kids)}</div>
    <label style="display:block;font-size:.85rem;color:#555;margin:6px 0 4px">Date (for one-day tasks)</label>
    <input type="date" name="date" value="{date_s or today_local().isoformat()}" style="{_INPUT}">
    <label style="display:block;font-size:.85rem;color:#555;margin:6px 0 4px">Repeat</label>
    <select name="kind" style="{_INPUT}">{_kind_options(kind)}</select>
    <div style="margin-bottom:6px">{_dow_checks(dows)}</div>
    <button style="display:block;width:100%;border:0;border-radius:12px;padding:15px 0;font-size:1.08rem;font-weight:600;color:#fff;background:#2f6fed;cursor:pointer;margin-top:6px" type="submit">Save task</button>
  </form>
</div>"""

def parse_task_form(f):
    """Validate quick-add/edit fields. Returns (title, kids, kind, date_s, dows) or raises ValueError."""
    title = (f.get("title", "") or "").strip()[:120]
    if not title:
        raise ValueError("Give the task a name")
    kids = [k for k in KIDS if f.get(f"kid_{k}")]
    if not kids:
        raise ValueError("Pick at least one kid")
    kind = f.get("kind", "once")
    if kind not in ("once", "daily", "weekly"):
        kind = "once"
    date_s = f.get("date", "") or today_local().isoformat()
    try:
        date.fromisoformat(date_s)
    except ValueError:
        date_s = today_local().isoformat()
    dows = sorted(i for i in range(7) if f.get(f"dow_{i}"))
    if kind == "weekly" and not dows:
        raise ValueError("Pick at least one weekday for a weekly task")
    return title, kids, kind, date_s, dows
