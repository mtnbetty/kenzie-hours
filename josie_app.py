#!/usr/bin/env python3
"""Josie's daily math practice - 8th grade / algebra readiness. Served by app.py.

Skills (difficulty scales with her recent accuracy):
  - one-step and two-step equations (integer answers)
  - exponents and square roots
  - fraction arithmetic (answers as reduced fractions, e.g. 5/6)
  - percents
  - slope between two points
  - order of operations

Kid view: /j/<JOSIE_TOKEN> - ~20 min daily set, one problem at a time, retry flow
Parent view: served inside the unified dashboard (app.py) via parent_sections()
"""
import os, json, sqlite3, secrets, random
from fractions import Fraction
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo

import reading_app

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "josie.db")
TOKENS_PATH = os.path.join(DATA_DIR, "josie-tokens.json")
TZ = ZoneInfo("America/Denver")

MIX = {"one_step": 3, "two_step": 3, "exponents": 2, "fractions": 2,
       "percents": 2, "slope": 1, "order_ops": 2}
PROBLEMS_PER_DAY = sum(MIX.values())
SKILL_ORDER = ["one_step", "two_step", "exponents", "fractions", "percents", "slope", "order_ops"]
SKILL_LABEL = {"one_step": "One-step equations", "two_step": "Two-step equations",
               "exponents": "Exponents & roots", "fractions": "Fractions",
               "percents": "Percents", "slope": "Slope", "order_ops": "Order of operations"}

CHEER = ["Nice.", "Correct.", "That's it.", "Clean.", "Exactly right.", "Good work.", "Yep. Keep going."]
CHEER2 = ["There it is.", "Got it on the retry.", "Good recovery."]
COMFORT = ["Not quite - one more try.", "Close. Try it again.", "Check your work and take another shot."]

os.makedirs(DATA_DIR, exist_ok=True)

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL UNIQUE,
        started TEXT NOT NULL,
        finished TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS problems(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        idx INTEGER NOT NULL,
        skill TEXT NOT NULL,
        prompt TEXT NOT NULL,
        answer TEXT NOT NULL,
        josie_answer TEXT,
        correct INTEGER,
        first_try INTEGER,
        attempts INTEGER NOT NULL DEFAULT 0,
        seconds REAL,
        shown_at TEXT,
        answered_at TEXT)""")
    return con

def load_tokens():
    jt = os.environ.get("JOSIE_TOKEN")
    if jt:
        return jt
    if os.path.exists(TOKENS_PATH):
        return json.load(open(TOKENS_PATH))["josie"]
    jt = secrets.token_urlsafe(18)
    json.dump({"josie": jt}, open(TOKENS_PATH, "w"))
    return jt

JOSIE_TOKEN = load_tokens()

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def parse(s):
    return datetime.fromisoformat(s)

def today_local():
    return now_utc().astimezone(TZ).date()

def fmt_day(dstr):
    return date.fromisoformat(dstr).strftime("%a %b %-d")

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

# ---------- problem generation ----------

def skill_stats(con):
    rows = con.execute("""SELECT skill, COUNT(*), SUM(correct) FROM problems
                          WHERE correct IS NOT NULL GROUP BY skill""").fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}

def skill_level(con, skill):
    n, c = skill_stats(con).get(skill, (0, 0))
    if not n or n < 8:
        return 1
    acc = c / n
    if acc >= 0.9 and n >= 15:
        return 3
    if acc >= 0.7:
        return 2
    return 1

def gen_one_step(rng, level):
    kind = rng.choice(["add", "sub", "mul", "div"])
    xmax = 12 + level * 4
    if kind == "add":
        x = rng.randint(-10, xmax) if level >= 2 else rng.randint(1, xmax)
        a = rng.randint(2, 6 + level * 3)
        return f"x + {a} = {x + a}", str(x)
    if kind == "sub":
        x = rng.randint(-10, xmax) if level >= 2 else rng.randint(1, xmax)
        a = rng.randint(2, 6 + level * 3)
        return f"x - {a} = {x - a}", str(x)
    if kind == "mul":
        a = rng.randint(2, 5 + level * 2)
        if level >= 2 and rng.random() < 0.4:
            a = -a
        x = rng.choice([i for i in range(-9, 13) if i != 0]) if level >= 2 else rng.randint(2, 12)
        return f"{a}x = {a * x}", str(x)
    x = rng.randint(2, 12)
    a = rng.randint(2, 12)
    return f"x / {a} = {x}", str(x * a)

def gen_two_step(rng, level):
    a = rng.randint(2, 5 + level)
    if level >= 2 and rng.random() < 0.35:
        a = -a
    x = rng.choice([i for i in range(-8, 13) if i != 0]) if level >= 2 else rng.randint(1, 12)
    b = rng.randint(1, 6 + level * 3)
    sign = rng.choice([1, -1])
    c = a * x + sign * b
    op = "+" if sign > 0 else "-"
    return f"{a}x {op} {b} = {c}", str(x)

def gen_exponents(rng, level):
    kind = rng.choice(["pow", "pow", "root", "neg", "zero"] if level >= 2 else ["pow", "pow", "root"])
    if kind == "root":
        r = rng.randint(2, 15 + level)
        return f"sqrt({r*r}) = ?", str(r)
    if kind == "neg":
        b = rng.randint(2, 5 + level)
        e = rng.choice([2, 2, 3])
        return f"(-{b})^{e} = ?", str((-b) ** e)
    if kind == "zero":
        b = rng.randint(2, 30)
        return f"{b}^0 = ?", "1"
    b = rng.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    e = rng.choice([2, 2, 2, 3, 3])
    if level >= 3 and b <= 3 and rng.random() < 0.4:
        e = rng.choice([4, 5])
    return f"{b}^{e} = ?", str(b ** e)

def gen_fractions(rng, level):
    denoms = {1: [2, 3, 4, 6], 2: [2, 3, 4, 5, 6, 8, 10, 12], 3: [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15]}[level]
    kind = rng.choice(["add", "sub", "mul", "simplify"])
    def rf():
        d = rng.choice(denoms)
        n = rng.randint(1, d - 1)
        return Fraction(n, d)
    if kind == "simplify":
        r = rf()
        k = rng.randint(2, 9)
        return f"Simplify {r.numerator * k}/{r.denominator * k}", str(r)
    f1, f2 = rf(), rf()
    if kind == "add":
        return f"{f1} + {f2} = ?", str(f1 + f2)
    if kind == "sub":
        if level < 3 and f2 > f1:
            f1, f2 = f2, f1
        return f"{f1} - {f2} = ?", str(f1 - f2)
    return f"{f1} x {f2} = ?", str(f1 * f2)

def gen_percents(rng, level):
    kind = rng.choice(["of", "whatpct", "reverse"] if level >= 2 else ["of", "of", "whatpct"])
    p = rng.choice([5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 65, 70, 75, 80, 85, 90, 95])
    n = 20 * rng.randint(1, 8 + level * 2)
    m = p * n // 100
    if kind == "of":
        return f"What is {p}% of {n}?", str(m)
    if kind == "whatpct":
        return f"{m} is what percent of {n}?", str(p)
    return f"{m} is {p}% of what number?", str(n)

def gen_slope(rng, level):
    x1, y1 = rng.randint(-5, 5), rng.randint(-8, 8)
    dx = rng.randint(1, 6)
    if level >= 3 and rng.random() < 0.5:
        dy = rng.choice([i for i in range(-9, 10) if i % dx != 0]) or dx
    else:
        dy = rng.randint(-4, 4) * dx
    s = Fraction(dy, dx)
    return (f"Find the slope of the line through ({x1}, {y1}) and ({x1 + dx}, {y1 + dy})",
            str(s))

def gen_order_ops(rng, level):
    hi = 6 + level * 3
    t = rng.randint(1, 5)
    if t == 1:
        a, b, c = rng.randint(2, hi), rng.randint(2, 9), rng.randint(2, 9)
        return f"{a} + {b} x {c}", str(a + b * c)
    if t == 2:
        a, b, c = rng.randint(2, hi), rng.randint(2, hi), rng.randint(2, 9)
        return f"({a} + {b}) x {c}", str((a + b) * c)
    if t == 3:
        a, b, c = rng.randint(2, hi), rng.randint(2, 9), rng.randint(2, hi * 2)
        return f"{a} x {b} - {c}", str(a * b - c)
    if t == 4:
        a, b, c = rng.randint(2, 3 + level), rng.randint(2, 9), rng.randint(2, 9)
        return f"{a}^2 + {b} x {c}", str(a * a + b * c)
    a, b, c, d = rng.randint(2, hi), rng.randint(1, hi - 1), rng.randint(2, 6), rng.randint(1, 6)
    return f"({a} - {b}) x ({c} + {d})", str((a - b) * (c + d))

GENERATORS = {"one_step": gen_one_step, "two_step": gen_two_step, "exponents": gen_exponents,
              "fractions": gen_fractions, "percents": gen_percents, "slope": gen_slope,
              "order_ops": gen_order_ops}
FRACTION_HINT = {"fractions", "slope"}

def gen_problems(con, day):
    """Deterministic per-day set; skills she's weak in get extra reps."""
    rng = random.Random(int(day.strftime("%Y%m%d")) + 7)
    mix = dict(MIX)
    stats = skill_stats(con)
    weak = [s for s in SKILL_ORDER if stats.get(s, (0, 0))[0] >= 5 and stats[s][1] / stats[s][0] < 0.6]
    strong = [s for s in SKILL_ORDER if stats.get(s, (0, 0))[0] >= 5 and stats[s][1] / stats[s][0] >= 0.85 and mix[s] > 1]
    for s in weak[:2]:
        mix[s] += 1
        if strong:
            mix[strong.pop(0)] -= 1
    probs = []
    for skill in SKILL_ORDER:
        level = skill_level(con, skill)
        for _ in range(mix[skill]):
            probs.append((skill,) + GENERATORS[skill](rng, level))
    return probs

def parse_answer(s):
    s = str(s).strip().lower().replace(" ", "")
    for pre in ("x=", "x ="):
        if s.startswith(pre):
            s = s[len(pre):]
    if not s:
        raise ValueError("empty")
    return Fraction(s)

# ---------- session management ----------

def get_or_create_session(con):
    day = today_local()
    row = con.execute("SELECT id, day, started, finished FROM sessions WHERE day=?",
                      (day.isoformat(),)).fetchone()
    if row:
        return {"id": row[0], "day": row[1], "started": row[2], "finished": row[3]}
    con.execute("INSERT INTO sessions(day, started) VALUES (?,?)", (day.isoformat(), iso(now_utc())))
    sid = con.execute("SELECT id FROM sessions WHERE day=?", (day.isoformat(),)).fetchone()[0]
    for i, (skill, prompt, answer) in enumerate(gen_problems(con, day)):
        con.execute("INSERT INTO problems(session_id, idx, skill, prompt, answer) VALUES (?,?,?,?,?)",
                    (sid, i, skill, prompt, answer))
    con.commit()
    return {"id": sid, "day": day.isoformat(), "started": iso(now_utc()), "finished": None}

def current_problem(con, sid):
    row = con.execute("""SELECT id, idx, skill, prompt, answer, josie_answer, correct, attempts
                         FROM problems WHERE session_id=? AND correct IS NULL
                         ORDER BY idx LIMIT 1""", (sid,)).fetchone()
    if not row:
        return None
    con.execute("UPDATE problems SET shown_at=? WHERE id=?", (iso(now_utc()), row[0]))
    con.commit()
    return {"id": row[0], "idx": row[1], "skill": row[2], "prompt": row[3],
            "answer": row[4], "attempts": row[7]}

def session_stats(con, sid):
    done = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct IS NOT NULL", (sid,)).fetchone()[0]
    right = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct=1", (sid,)).fetchone()[0]
    first = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct=1 AND first_try=1", (sid,)).fetchone()[0]
    return done, right, first

def finish_if_done(con, sid):
    done, right, first = session_stats(con, sid)
    total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (sid,)).fetchone()[0]
    if total and done >= total:
        s = con.execute("SELECT finished FROM sessions WHERE id=?", (sid,)).fetchone()
        if not s[0]:
            con.execute("UPDATE sessions SET finished=? WHERE id=?", (iso(now_utc()), sid))
            con.commit()
        return True
    return False

def streak(con):
    days = {r[0] for r in con.execute("SELECT day FROM sessions WHERE finished IS NOT NULL").fetchall()}
    if not days:
        return 0
    n, d = 0, today_local()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n

# ---------- kid pages ----------

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0e7490">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f2f6f7; color: #17303a; padding: 16px; max-width: 560px; margin: 0 auto; }}
h1 {{ font-size: 1.45rem; margin: 8px 0 4px; }}
.sub {{ color: #5b7180; font-size: .95rem; margin-bottom: 16px; }}
.card {{ background: #fff; border-radius: 14px; padding: 20px; margin-bottom: 14px;
  box-shadow: 0 2px 6px rgba(10,50,70,.10); }}
.bigbtn {{ display: block; width: 100%; border: 0; border-radius: 14px; padding: 22px 0;
  font-size: 1.35rem; font-weight: 700; color: #fff; background: #0e7490; cursor: pointer; }}
.bigbtn:active {{ transform: scale(.98); }}
.readbtn {{ background: #b45309; }}
.status {{ text-align: center; font-size: 1.05rem; margin-bottom: 12px; }}
.problem {{ text-align: center; font-size: 2.4rem; font-weight: 700; margin: 16px 0;
  font-variant-numeric: tabular-nums; }}
.skilltag {{ text-align: center; font-size: .82rem; font-weight: 700; color: #0e7490;
  text-transform: uppercase; letter-spacing: .08em; }}
input[type=text] {{ width: 100%; padding: 16px; font-size: 1.8rem; text-align: center;
  border: 2px solid #b8d4dd; border-radius: 12px; margin-bottom: 12px;
  font-variant-numeric: tabular-nums; }}
input[type=text]:focus {{ outline: none; border-color: #0e7490; }}
.flash {{ border-radius: 12px; padding: 13px; text-align: center; margin-bottom: 14px;
  font-weight: 600; font-size: 1rem; }}
.good {{ background: #e5f9ee; color: #177a3f; }}
.err {{ background: #fdecea; color: #a33; }}
.info {{ background: #eef2ff; color: #3d4db3; }}
.progress {{ background: #d3e5ea; border-radius: 99px; height: 12px; overflow: hidden; margin: 10px 0 4px; }}
.progress > div {{ background: #0e7490; height: 100%; border-radius: 99px; transition: width .3s; }}
.muted {{ color: #7a8b94; font-size: .85rem; }}
.center {{ text-align: center; }}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ text-align: left; padding: 7px 6px; border-bottom: 1px solid #e5ecef; }}
th {{ color: #6c7f89; font-weight: 600; font-size: .78rem; text-transform: uppercase; }}
.yes {{ color: #177a3f; font-weight: 700; }}
.no {{ color: #c0392b; font-weight: 700; }}
.bar {{ background: #d3e5ea; border-radius: 6px; height: 10px; overflow: hidden; min-width: 80px; }}
.bar > div {{ background: #0e7490; height: 100%; }}
a {{ color: #0e7490; }}
.statgrid {{ display: flex; gap: 10px; margin-bottom: 14px; }}
.stat {{ flex: 1; background: #fff; border-radius: 12px; padding: 14px 10px; text-align: center;
  box-shadow: 0 2px 6px rgba(10,50,70,.10); }}
.stat .n {{ font-size: 1.5rem; font-weight: 800; }}
.stat .l {{ font-size: .72rem; color: #6c7f89; text-transform: uppercase; letter-spacing: .05em; }}
h2 {{ font-size: 1.02rem; margin: 22px 0 8px; color: #44606e; }}
.subbtn {{ display: block; width: 100%; border: 0; border-radius: 12px; padding: 14px 0;
  font-size: 1.05rem; font-weight: 600; color: #fff; background: #0e7490; cursor: pointer; }}
</style></head><body>
{body}
</body></html>"""

def flash_html(msg):
    if not msg:
        return ""
    cls = "err" if msg.startswith("!") else ("good" if msg.startswith("+") else "info")
    return f'<div class="flash {cls}">{esc(msg.lstrip("!+"))}</div>'

def josie_home(con, msg=None):
    day = today_local()
    srow = con.execute("SELECT id, finished FROM sessions WHERE day=?", (day.isoformat(),)).fetchone()
    jbase = f"/j/{JOSIE_TOKEN}"
    fl = flash_html(msg)
    st = streak(con)
    streak_line = f'<div class="status">&#128293; <b>{st}-day streak</b></div>' if st > 0 else ""

    rcon = reading_app.db()
    try:
        r_already = reading_app.checked_today(rcon, "josie")
        r_streak = reading_app.streak(rcon, "josie")
    finally:
        rcon.close()
    reading_card = reading_app.kid_card(jbase, "josie", r_already, r_streak,
                                        "I read for 30 minutes")

    if srow and srow[1]:
        done, right, first = session_stats(con, srow[0])
        total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (srow[0],)).fetchone()[0]
        body = f"""
<h1>Hi Josie</h1>
<div class="sub">{fmt_day(day.isoformat())} - today's set is done</div>
{fl}
{streak_line}
<div class="card center">
  <div class="status">Today's set: <b>{right} of {total}</b> right, {first} on the first try.</div>
  <div class="muted">New set tomorrow. Your mom can see the results.</div>
</div>
{reading_card}"""
        return PAGE.format(title="Josie Math", body=body)

    if srow:
        done, right, first = session_stats(con, srow[0])
        total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (srow[0],)).fetchone()[0]
        pct = int(100 * done / total)
        body = f"""
<h1>Welcome back, Josie</h1>
<div class="sub">{fmt_day(day.isoformat())} - you're {done} of {total} in</div>
{fl}
{streak_line}
<div class="card">
  <div class="progress"><div style="width:{pct}%"></div></div>
  <div class="muted center" style="margin-bottom:12px">{done} of {total} done</div>
  <form method="post" action="{jbase}/play"><button class="bigbtn" type="submit">Keep going</button></form>
</div>
{reading_card}"""
        return PAGE.format(title="Josie Math", body=body)

    mixline = " &middot; ".join(f"{MIX[s]} {SKILL_LABEL[s].lower()}" for s in SKILL_ORDER if MIX[s])
    body = f"""
<h1>Hi Josie</h1>
<div class="sub">{fmt_day(day.isoformat())} - today's set: <b>{PROBLEMS_PER_DAY} problems</b>, about 20 minutes</div>
{fl}
{streak_line}
<div class="card">
  <div class="muted" style="margin-bottom:14px">Today's mix: {mixline}. One at a time, two tries each. It saves your progress if you need a break.</div>
  <form method="post" action="{jbase}/play"><button class="bigbtn" type="submit">Start today's set</button></form>
</div>
{reading_card}"""
    return PAGE.format(title="Josie Math", body=body)

def play_page(con, msg=None):
    s = get_or_create_session(con)
    jbase = f"/j/{JOSIE_TOKEN}"
    if finish_if_done(con, s["id"]):
        return None
    p = current_problem(con, s["id"])
    done, right, first = session_stats(con, s["id"])
    total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (s["id"],)).fetchone()[0]
    pct = int(100 * done / total)
    n = p["idx"] + 1
    retry = '<div class="flash err">Not quite - one more try on this one.</div>' if p["attempts"] == 1 else ""
    hint = '<div class="muted center">Fraction answers: type them like 5/6</div>' if p["skill"] in FRACTION_HINT else ""
    body = f"""
<div class="skilltag">{esc(SKILL_LABEL[p["skill"]])} &middot; problem {n} of {total}</div>
<div class="progress"><div style="width:{pct}%"></div></div>
{flash_html(msg)}
{retry}
<div class="card">
  <div class="problem">{esc(p["prompt"])}</div>
  <form method="post" action="{jbase}/answer" autocomplete="off">
    <input type="text" name="answer" inputmode="decimal" autocomplete="off"
      autocorrect="off" autocapitalize="off" spellcheck="false" required autofocus>
    <button class="bigbtn" type="submit">Check</button>
  </form>
  {hint}
</div>
<div class="muted center">{right} right so far today</div>
"""
    return PAGE.format(title=f"Problem {n}", body=body)

# ---------- parent sections (embedded in the unified dashboard) ----------

def parent_sections(con, parent_token):
    pbase = f"/parent/{parent_token}"
    st = streak(con)
    week_ago = (today_local() - timedelta(days=6)).isoformat()
    r7 = con.execute("""SELECT COUNT(*), SUM(p.correct) FROM problems p JOIN sessions s ON p.session_id=s.id
                        WHERE p.correct IS NOT NULL AND s.day>=?""", (week_ago,)).fetchone()
    acc7 = f"{int(100*r7[1]/r7[0])}%" if r7 and r7[0] else "-"
    nsess = con.execute("SELECT COUNT(*) FROM sessions WHERE finished IS NOT NULL").fetchone()[0]
    statgrid = f"""<div class="statgrid">
<div class="stat"><div class="n">&#128293; {st}</div><div class="l">day streak</div></div>
<div class="stat"><div class="n">{acc7}</div><div class="l">7-day accuracy</div></div>
<div class="stat"><div class="n">{nsess}</div><div class="l">sets finished</div></div>
</div>"""

    stats = skill_stats(con)
    sk_rows = ""
    for sk in SKILL_ORDER:
        if sk in stats:
            n, c = stats[sk]
            pct = int(100 * c / n)
            lvl = skill_level(con, sk)
            sk_rows += (f"<tr><td>{esc(SKILL_LABEL[sk])}</td><td>{c}/{n}</td>"
                        f'<td><div class="bar"><div style="width:{pct}%"></div></div></td>'
                        f"<td>{pct}%</td><td class='muted'>L{lvl}</td></tr>")
    skills_html = ""
    if sk_rows:
        skills_html = f"""<div class="card"><table>
<tr><th>Skill</th><th>Right</th><th></th><th>%</th><th>Level</th></tr>{sk_rows}</table>
<div class="muted" style="margin-top:6px">Levels rise as her accuracy climbs - higher level, harder problems. Weak skills automatically get extra reps.</div></div>"""

    sess = con.execute("SELECT id, day, started, finished FROM sessions ORDER BY day DESC LIMIT 30").fetchall()
    srows = ""
    for sid, d, started, finished in sess:
        done, right, first = session_stats(con, sid)
        total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (sid,)).fetchone()[0]
        state = "done" if finished else ("in progress" if done else "not started")
        mins = f"{(parse(finished)-parse(started)).total_seconds()/60:.0f} min" if started and finished else "-"
        srows += (f'<tr><td><a href="{pbase}/jsession/{sid}">{fmt_day(d)}</a></td>'
                  f"<td>{right}/{done or total}</td><td>{mins}</td><td>{state}</td></tr>")
    sess_html = f"""<div class="card"><table>
<tr><th>Day</th><th>Score</th><th>Time</th><th>Status</th></tr>
{srows or '<tr><td colspan="4" class="muted">No sessions yet.</td></tr>'}</table>
<div class="muted" style="margin-top:6px">Tap a day for every problem and her answers.</div></div>"""

    return f"""<h2 id="josie">Josie's math (8th grade)</h2>
{statgrid}
{skills_html}
{sess_html}"""

def session_page(con, sid, parent_token):
    s = con.execute("SELECT day, started, finished FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        return None
    done, right, first = session_stats(con, sid)
    total = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=?", (sid,)).fetchone()[0]
    probs = con.execute("""SELECT idx, skill, prompt, answer, josie_answer, correct, first_try, attempts, seconds
                           FROM problems WHERE session_id=? ORDER BY idx""", (sid,)).fetchall()
    rows = ""
    for idx, skill, prompt, ans, jans, correct, ft, att, secs in probs:
        if correct is None:
            mark, jcell, tcell = '<span class="muted">-</span>', "-", "-"
        else:
            mark = '<span class="yes">&#10003;</span>' if correct else '<span class="no">&#10007;</span>'
            if correct and not ft:
                mark += ' <span class="muted">(2nd try)</span>'
            jcell = esc(jans) if jans is not None else "-"
            if not correct:
                jcell = f'<span class="no">{jcell}</span> &rarr; <b>{esc(ans)}</b>'
            tcell = f"{secs:.0f}s" if secs is not None else "-"
        rows += (f"<tr><td>{esc(prompt)}</td><td class='muted'>{esc(SKILL_LABEL[skill])}</td>"
                 f"<td>{jcell}</td><td>{mark}</td><td>{tcell}</td></tr>")
    body = f"""
<h1>Josie - {fmt_day(s[0])} - {right} of {total} right</h1>
<div class="sub">{first} on the first try &middot; <a href="/parent/{parent_token}">back to the dashboard</a></div>
<div class="card"><table>
<tr><th>Problem</th><th>Skill</th><th>Her answer</th><th></th><th>Time</th></tr>
{rows}
</table></div>
<div class="card center">
<form method="post" action="/parent/{parent_token}/del_jsession/{sid}">
<button class="subbtn" style="background:#c0392b" type="submit">Delete this session's data</button>
</form>
<div class="muted" style="margin-top:6px">Removes this day from her history and stats (useful for test runs).</div>
</div>"""
    return PAGE.format(title=f"Josie {fmt_day(s[0])}", body=body)

# ---------- routing ----------

def wants(parts):
    return bool(parts) and parts[0] == "j"

def do_get(h, parts, msg):
    con = db()
    try:
        if parts == ["j", JOSIE_TOKEN]:
            h._send(200, josie_home(con, msg))
        elif parts == ["j", JOSIE_TOKEN, "play"]:
            page = play_page(con, msg)
            if page is None:
                h._redirect(f"/j/{JOSIE_TOKEN}", "+Set complete - nice work today.")
            else:
                h._send(200, page)
        else:
            h._send(404, "not found", "text/plain")
    finally:
        con.close()

def do_post(h, parts):
    if len(parts) == 3 and parts[0] == "j" and parts[1] == JOSIE_TOKEN and parts[2] == "reading":
        rcon = reading_app.db()
        try:
            new = reading_app.mark_today(rcon, "josie")
        finally:
            rcon.close()
        h._redirect(f"/j/{JOSIE_TOKEN}", "+Reading logged - 30 minutes, done." if new else "Reading was already logged today.")
        return
    con = db()
    try:
        if len(parts) == 3 and parts[0] == "j" and parts[1] == JOSIE_TOKEN and parts[2] in ("start", "play"):
            get_or_create_session(con)
            h._redirect(f"/j/{JOSIE_TOKEN}/play")
        elif len(parts) == 3 and parts[0] == "j" and parts[1] == JOSIE_TOKEN and parts[2] == "answer":
            f = h._post_fields()
            s = get_or_create_session(con)
            p = current_problem(con, s["id"])
            if p is None:
                h._redirect(f"/j/{JOSIE_TOKEN}")
                return
            try:
                guess = parse_answer(f.get("answer", ""))
            except (ValueError, ZeroDivisionError):
                h._redirect(f"/j/{JOSIE_TOKEN}/play", "!Type your answer as a number or fraction (like 5/6)")
                return
            guess_raw = str(f.get("answer", "")).strip()
            attempts = p["attempts"] + 1
            if guess == Fraction(p["answer"]):
                row = con.execute("SELECT shown_at FROM problems WHERE id=?", (p["id"],)).fetchone()
                secs = max(0.0, (now_utc() - parse(row[0])).total_seconds()) if row and row[0] else None
                con.execute("""UPDATE problems SET josie_answer=?, correct=1, first_try=?, attempts=?,
                               seconds=?, answered_at=? WHERE id=?""",
                            (guess_raw, 1 if attempts == 1 else 0, attempts, secs, iso(now_utc()), p["id"]))
                con.commit()
                cheer = secrets.choice(CHEER if attempts == 1 else CHEER2)
                if finish_if_done(con, s["id"]):
                    h._redirect(f"/j/{JOSIE_TOKEN}", "+Set complete - nice work today.")
                else:
                    h._redirect(f"/j/{JOSIE_TOKEN}/play", "+" + cheer)
            else:
                if attempts >= 2:
                    row = con.execute("SELECT shown_at FROM problems WHERE id=?", (p["id"],)).fetchone()
                    secs = max(0.0, (now_utc() - parse(row[0])).total_seconds()) if row and row[0] else None
                    con.execute("""UPDATE problems SET josie_answer=?, correct=0, first_try=0, attempts=?,
                                   seconds=?, answered_at=? WHERE id=?""",
                                (guess_raw, attempts, secs, iso(now_utc()), p["id"]))
                    con.commit()
                    h._redirect(f"/j/{JOSIE_TOKEN}/play",
                                f"!Answer: {p['answer']}. On to the next one.")
                else:
                    con.execute("UPDATE problems SET attempts=? WHERE id=?", (attempts, p["id"]))
                    con.commit()
                    h._redirect(f"/j/{JOSIE_TOKEN}/play")
        else:
            h._send(404, "not found", "text/plain")
    finally:
        con.close()
