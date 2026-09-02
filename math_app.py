#!/usr/bin/env python3
"""Goldie's daily math practice module. Served by app.py alongside kenzie-hours.

Skills targeted (per her teacher, Mrs. Derderian, 2026-09-01):
  - basic multiplication facts (times tables)
  - 2-digit x 2-digit multiplication
  - 3-digit x 2-digit multiplication

Kid view:    /g/<GOLDIE_TOKEN>   - daily check-in + ~20 min problem set
Parent view: /parent/<PARENT_TOKEN> - per-problem results, weak spots, progress
"""
import os, json, sqlite3, secrets, random, base64
from datetime import datetime, timezone, timedelta, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "math.db")
TOKENS_PATH = os.path.join(DATA_DIR, "math-tokens.json")
TZ = ZoneInfo("America/Denver")
PORT = int(os.environ.get("PORT", "8080"))

N_FACTS, N_2X2, N_3X2 = 12, 6, 4
PROBLEMS_PER_DAY = N_FACTS + N_2X2 + N_3X2

os.makedirs(DATA_DIR, exist_ok=True)

SKILL_LABEL = {"facts": "Times tables", "2x2": "2-digit x 2-digit", "3x2": "3-digit x 2-digit"}
SKILL_ORDER = ["facts", "2x2", "3x2"]

CHEER = ["Nice!", "You got it!", "Boom!", "Nailed it!", "Way to go!", "Star work!", "Exactly right!", "Keep rolling!"]
CHEER2 = ["Good save!", "There it is!", "Knew you'd get it!", "Second-try star!"]
COMFORT = ["Not quite - one more try!", "So close! Try again.", "Take a breath, one more shot.", "You've got this - try once more."]

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL UNIQUE,
        started TEXT NOT NULL,
        finished TEXT,
        mood TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS problems(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        idx INTEGER NOT NULL,
        skill TEXT NOT NULL,
        a INTEGER NOT NULL,
        b INTEGER NOT NULL,
        answer INTEGER NOT NULL,
        goldie_answer INTEGER,
        correct INTEGER,
        first_try INTEGER,
        attempts INTEGER NOT NULL DEFAULT 0,
        seconds REAL,
        shown_at TEXT,
        answered_at TEXT)""")
    return con

def load_tokens():
    gt, pt = os.environ.get("GOLDIE_TOKEN"), os.environ.get("PARENT_TOKEN")
    if gt and pt:
        return gt, pt
    if os.path.exists(TOKENS_PATH):
        t = json.load(open(TOKENS_PATH))
        return t["goldie"], t["parent"]
    gt, pt = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    json.dump({"goldie": gt, "parent": pt}, open(TOKENS_PATH, "w"))
    return gt, pt

GOLDIE_TOKEN, PARENT_TOKEN = load_tokens()

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def parse(s):
    return datetime.fromisoformat(s)

def today_local():
    return now_utc().astimezone(TZ).date()

def fmt_day(dstr):
    d = date.fromisoformat(dstr)
    return d.strftime("%a %b %-d")

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

# ---------- problem generation ----------

def missed_fact_weights(con):
    """How many times each times-table fact has been missed, keyed by (a,b) with a<=b."""
    w = {}
    for a, b in con.execute(
            "SELECT a, b FROM problems WHERE skill='facts' AND correct=0").fetchall():
        k = (min(a, b), max(a, b))
        w[k] = w.get(k, 0) + 1
    return w

def gen_problems(con, day):
    """Deterministic per-day set, weighted toward facts she has missed before."""
    rng = random.Random(int(day.strftime("%Y%m%d")))
    probs = []
    weights = missed_fact_weights(con)
    pool = [(a, b) for a in range(2, 13) for b in range(2, 13)]
    for _ in range(N_FACTS):
        missed = [k for k in pool if weights.get(k, 0) > 0]
        if missed and rng.random() < 0.6:
            k = rng.choice(missed)
        else:
            k = rng.choice(pool)
        a, b = k
        if rng.random() < 0.5:
            a, b = b, a
        probs.append(("facts", a, b))
    for _ in range(N_2X2):
        probs.append(("2x2", rng.randint(10, 99), rng.randint(10, 99)))
    for _ in range(N_3X2):
        probs.append(("3x2", rng.randint(100, 999), rng.randint(10, 99)))
    return probs

def get_or_create_session(con):
    day = today_local()
    row = con.execute("SELECT id, day, started, finished, mood FROM sessions WHERE day=?",
                      (day.isoformat(),)).fetchone()
    if row:
        return {"id": row[0], "day": row[1], "started": row[2], "finished": row[3], "mood": row[4]}
    con.execute("INSERT INTO sessions(day, started) VALUES (?,?)", (day.isoformat(), iso(now_utc())))
    sid = con.execute("SELECT id FROM sessions WHERE day=?", (day.isoformat(),)).fetchone()[0]
    for i, (skill, a, b) in enumerate(gen_problems(con, day)):
        con.execute("INSERT INTO problems(session_id, idx, skill, a, b, answer) VALUES (?,?,?,?,?,?)",
                    (sid, i, skill, a, b, a * b))
    con.commit()
    return {"id": sid, "day": day.isoformat(), "started": iso(now_utc()), "finished": None, "mood": None}

def current_problem(con, sid):
    row = con.execute("""SELECT id, idx, skill, a, b, answer, goldie_answer, correct, attempts
                         FROM problems WHERE session_id=? AND correct IS NULL
                         ORDER BY idx LIMIT 1""", (sid,)).fetchone()
    if not row:
        return None
    con.execute("UPDATE problems SET shown_at=? WHERE id=?", (iso(now_utc()), row[0]))
    con.commit()
    return {"id": row[0], "idx": row[1], "skill": row[2], "a": row[3], "b": row[4],
            "answer": row[5], "attempts": row[8]}

def session_stats(con, sid):
    done = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct IS NOT NULL", (sid,)).fetchone()[0]
    right = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct=1", (sid,)).fetchone()[0]
    first = con.execute("SELECT COUNT(*) FROM problems WHERE session_id=? AND correct=1 AND first_try=1", (sid,)).fetchone()[0]
    return done, right, first

def finish_if_done(con, sid):
    done, right, first = session_stats(con, sid)
    if done >= PROBLEMS_PER_DAY:
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

def total_stars(con):
    return con.execute("SELECT COUNT(*) FROM problems WHERE correct=1").fetchone()[0]

# ---------- pages ----------

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#7b5cff">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f6f4ff; color: #241f3a; padding: 16px; max-width: 560px; margin: 0 auto; }}
h1 {{ font-size: 1.5rem; margin: 8px 0 4px; }}
h2 {{ font-size: 1.05rem; margin: 24px 0 8px; color: #555; }}
.sub {{ color: #6b6685; font-size: .95rem; margin-bottom: 16px; }}
.card {{ background: #fff; border-radius: 16px; padding: 20px; margin-bottom: 14px;
  box-shadow: 0 2px 6px rgba(60,40,120,.10); }}
.bigbtn {{ display: block; width: 100%; border: 0; border-radius: 18px; padding: 26px 0;
  font-size: 1.5rem; font-weight: 800; color: #fff; background: #7b5cff; cursor: pointer; }}
.bigbtn:active {{ transform: scale(.98); }}
.status {{ text-align: center; font-size: 1.1rem; margin-bottom: 12px; }}
.problem {{ text-align: center; font-size: 3.2rem; font-weight: 800; margin: 14px 0;
  font-variant-numeric: tabular-nums; letter-spacing: .02em; }}
.skilltag {{ text-align: center; font-size: .85rem; font-weight: 700; color: #7b5cff;
  text-transform: uppercase; letter-spacing: .08em; }}
input[type=number] {{ width: 100%; padding: 18px; font-size: 2rem; text-align: center;
  border: 2px solid #cfc6f5; border-radius: 14px; margin-bottom: 12px;
  font-variant-numeric: tabular-nums; }}
input[type=number]:focus {{ outline: none; border-color: #7b5cff; }}
.flash {{ border-radius: 12px; padding: 14px; text-align: center; margin-bottom: 14px;
  font-weight: 700; font-size: 1.05rem; }}
.good {{ background: #e5f9ee; color: #177a3f; }}
.err {{ background: #fdecea; color: #a33; }}
.info {{ background: #eef2ff; color: #3d4db3; }}
.progress {{ background: #e7e2fa; border-radius: 99px; height: 14px; overflow: hidden; margin: 10px 0 4px; }}
.progress > div {{ background: #7b5cff; height: 100%; border-radius: 99px; transition: width .3s; }}
.muted {{ color: #888; font-size: .85rem; }}
.center {{ text-align: center; }}
.stars {{ font-size: 2rem; text-align: center; margin: 8px 0; }}
.moods {{ display: flex; gap: 12px; justify-content: center; margin: 12px 0 4px; }}
.moods button {{ font-size: 2.2rem; background: #f1edff; border: 2px solid transparent;
  border-radius: 14px; padding: 8px 14px; cursor: pointer; }}
.moods button:active {{ border-color: #7b5cff; }}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ text-align: left; padding: 7px 6px; border-bottom: 1px solid #eee; }}
th {{ color: #777; font-weight: 600; font-size: .78rem; text-transform: uppercase; }}
.yes {{ color: #177a3f; font-weight: 700; }}
.no {{ color: #c0392b; font-weight: 700; }}
.bar {{ background: #e7e2fa; border-radius: 6px; height: 10px; overflow: hidden; min-width: 80px; }}
.bar > div {{ background: #7b5cff; height: 100%; }}
a {{ color: #5b3ff0; }}
.statgrid {{ display: flex; gap: 10px; margin-bottom: 14px; }}
.stat {{ flex: 1; background: #fff; border-radius: 14px; padding: 14px 10px; text-align: center;
  box-shadow: 0 2px 6px rgba(60,40,120,.10); }}
.stat .n {{ font-size: 1.6rem; font-weight: 800; }}
.stat .l {{ font-size: .75rem; color: #777; text-transform: uppercase; letter-spacing: .05em; }}
.confetti {{ position: fixed; top: -10px; width: 10px; height: 14px; opacity: .9;
  animation: fall linear forwards; pointer-events: none; z-index: 50; }}
@keyframes fall {{ to {{ transform: translateY(105vh) rotate(720deg); opacity: .6; }} }}
</style></head><body>
{body}
</body></html>"""

CONFETTI_JS = """
<script>
(function(){
  var colors=['#7b5cff','#ffcf40','#4ed08a','#ff7aa2','#4fb6ff'];
  for(var i=0;i<60;i++){
    var d=document.createElement('div');d.className='confetti';
    d.style.left=(Math.random()*100)+'vw';
    d.style.background=colors[i%colors.length];
    d.style.animationDuration=(2+Math.random()*2)+'s';
    d.style.animationDelay=(Math.random()*0.8)+'s';
    d.style.borderRadius=(Math.random()<0.5?'50%':'2px');
    document.body.appendChild(d);
  }
  setTimeout(function(){document.querySelectorAll('.confetti').forEach(function(e){e.remove();});},5000);
})();
</script>"""

def flash_html(msg):
    if not msg:
        return ""
    cls = "err" if msg.startswith("!") else ("good" if msg.startswith("+") else "info")
    return f'<div class="flash {cls}">{esc(msg.lstrip("!+"))}</div>'

def goldie_home(con, msg=None):
    day = today_local()
    srow = con.execute("SELECT id, finished, mood FROM sessions WHERE day=?", (day.isoformat(),)).fetchone()
    gbase = f"/g/{GOLDIE_TOKEN}"
    fl = flash_html(msg)
    st = streak(con)
    stars = total_stars(con)
    streak_line = ""
    if st > 0:
        streak_line = f'<div class="status">&#128293; <b>{st}-day streak!</b> &nbsp; &#11088; {stars} stars earned</div>'
    elif stars > 0:
        streak_line = f'<div class="status">&#11088; {stars} stars earned so far</div>'

    if srow and srow[1]:
        done, right, first = session_stats(con, srow[0])
        body = f"""
<h1>Hi Goldie! &#128075;</h1>
<div class="sub">{fmt_day(day.isoformat())} - today's mission is complete</div>
{fl}
{streak_line}
<div class="card center">
  <div class="stars">&#127775;</div>
  <div class="status">You finished today's math! <b>{right} of {PROBLEMS_PER_DAY}</b> right
  ({first} on the first try).</div>
  <div class="muted">Come back tomorrow to keep your streak going. Your mom can see how you did.</div>
</div>
{{confetti}}"""
        return PAGE.format(title="Goldie Math", body=body.format(confetti=CONFETTI_JS))

    if srow:
        done, right, first = session_stats(con, srow[0])
        pct = int(100 * done / PROBLEMS_PER_DAY)
        body = f"""
<h1>Welcome back, Goldie!</h1>
<div class="sub">{fmt_day(day.isoformat())} - you're {done} of {PROBLEMS_PER_DAY} problems in</div>
{fl}
{streak_line}
<div class="card">
  <div class="progress"><div style="width:{pct}%"></div></div>
  <div class="muted center" style="margin-bottom:12px">{done} of {PROBLEMS_PER_DAY} done - keep going!</div>
  <form method="post" action="{gbase}/play"><button class="bigbtn" type="submit">Keep going</button></form>
</div>"""
        return PAGE.format(title="Goldie Math", body=body)

    body = f"""
<h1>Hi Goldie! &#128075;</h1>
<div class="sub">{fmt_day(day.isoformat())} - today's mission: <b>{PROBLEMS_PER_DAY} problems</b>, about 20 minutes</div>
{fl}
{streak_line}
<div class="card">
  <div class="status">How are you feeling today?</div>
  <div class="moods">
    <form method="post" action="{gbase}/start"><input type="hidden" name="mood" value="great"><button type="submit">&#128513;</button></form>
    <form method="post" action="{gbase}/start"><input type="hidden" name="mood" value="ok"><button type="submit">&#128578;</button></form>
    <form method="post" action="{gbase}/start"><input type="hidden" name="mood" value="tired"><button type="submit">&#128564;</button></form>
  </div>
  <div class="muted center" style="margin:10px 0 14px">Pick one to check in, then your mission starts</div>
  <div class="card" style="box-shadow:none;background:#f6f4ff;margin:0">
    Today's mix:<br>
    &#10148; {N_FACTS} times-table warm-ups<br>
    &#10148; {N_2X2} two-digit times two-digit<br>
    &#10148; {N_3X2} big ones: three-digit times two-digit
  </div>
</div>"""
    return PAGE.format(title="Goldie Math", body=body)

def play_page(con, msg=None):
    s = get_or_create_session(con)
    gbase = f"/g/{GOLDIE_TOKEN}"
    if finish_if_done(con, s["id"]):
        return None  # caller redirects home
    p = current_problem(con, s["id"])
    done, right, first = session_stats(con, s["id"])
    pct = int(100 * done / PROBLEMS_PER_DAY)
    n = p["idx"] + 1
    label = SKILL_LABEL[p["skill"]]
    retry = ""
    if p["attempts"] == 1:
        retry = '<div class="flash err">Not quite - you have one more try on this one!</div>'
    body = f"""
<div class="skilltag">{esc(label)} &middot; problem {n} of {PROBLEMS_PER_DAY}</div>
<div class="progress"><div style="width:{pct}%"></div></div>
{flash_html(msg)}
{retry}
<div class="card">
  <div class="problem">{p["a"]} &times; {p["b"]} = ?</div>
  <form method="post" action="{gbase}/answer" autocomplete="off">
    <input type="number" name="answer" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
      autocorrect="off" autocapitalize="off" min="0" max="99999999" required autofocus>
    <button class="bigbtn" type="submit">Check it</button>
  </form>
</div>
<div class="muted center">&#11088; {right} right so far today</div>
"""
    return PAGE.format(title=f"Problem {n}", body=body)

def parent_page(con):
    pbase = f"/parent/{PARENT_TOKEN}"
    st = streak(con)
    stars = total_stars(con)
    # accuracy by skill (all time)
    rows = con.execute("""SELECT skill, COUNT(*), SUM(correct), SUM(CASE WHEN first_try=1 THEN 1 ELSE 0 END)
                          FROM problems WHERE correct IS NOT NULL GROUP BY skill""").fetchall()
    by_skill = {r[0]: (r[1], r[2], r[3]) for r in rows}
    # last 7 days accuracy
    week_ago = (today_local() - timedelta(days=6)).isoformat()
    r7 = con.execute("""SELECT COUNT(*), SUM(p.correct) FROM problems p JOIN sessions s ON p.session_id=s.id
                        WHERE p.correct IS NOT NULL AND s.day>=?""", (week_ago,)).fetchone()
    acc7 = f"{int(100*r7[1]/r7[0])}%" if r7 and r7[0] else "-"
    statgrid = f"""<div class="statgrid">
<div class="stat"><div class="n">&#128293; {st}</div><div class="l">day streak</div></div>
<div class="stat"><div class="n">&#11088; {stars}</div><div class="l">total stars</div></div>
<div class="stat"><div class="n">{acc7}</div><div class="l">7-day accuracy</div></div>
</div>"""

    # weak spots: most-missed facts
    misses = con.execute("""SELECT a, b, COUNT(*) c FROM problems
                            WHERE skill='facts' AND correct=0
                            GROUP BY min(a,b), max(a,b) ORDER BY c DESC, a, b LIMIT 8""").fetchall()
    weak = ""
    if misses:
        wrows = "".join(f"<tr><td><b>{a} &times; {b}</b></td><td>{c} miss{'es' if c>1 else ''}</td></tr>" for a, b, c in misses)
        weak = f"""<h2>Tricky times tables to practice together</h2>
<div class="card"><table><tr><th>Fact</th><th>Times missed</th></tr>{wrows}</table>
<div class="muted" style="margin-top:8px">These get extra repeats in her daily warm-ups automatically.</div></div>"""

    # skill breakdown
    sk_rows = ""
    for sk in SKILL_ORDER:
        if sk in by_skill:
            n, c, f1 = by_skill[sk]
            pct = int(100 * c / n)
            sk_rows += (f"<tr><td>{esc(SKILL_LABEL[sk])}</td><td>{c}/{n}</td>"
                        f'<td><div class="bar"><div style="width:{pct}%"></div></div></td><td>{pct}%</td></tr>')
    skills_html = ""
    if sk_rows:
        skills_html = f"""<h2>Accuracy by skill</h2>
<div class="card"><table><tr><th>Skill</th><th>Right</th><th></th><th>%</th></tr>{sk_rows}</table></div>"""

    # sessions
    sess = con.execute("SELECT id, day, started, finished, mood FROM sessions ORDER BY day DESC LIMIT 30").fetchall()
    srows = ""
    mood_map = {"great": "&#128513;", "ok": "&#128578;", "tired": "&#128564;"}
    for sid, d, started, finished, mood in sess:
        done, right, first = session_stats(con, sid)
        state = "done" if finished else ("in progress" if done else "not started")
        mins = ""
        if started and finished:
            mins = f"{(parse(finished)-parse(started)).total_seconds()/60:.0f} min"
        srows += (f'<tr><td><a href="{pbase}/session/{sid}">{fmt_day(d)}</a></td>'
                  f"<td>{mood_map.get(mood,'')}</td><td>{right}/{done or PROBLEMS_PER_DAY}</td>"
                  f"<td>{mins or '-'}</td><td>{state}</td></tr>")
    sess_html = f"""<h2>Daily sessions</h2>
<div class="card"><table><tr><th>Day</th><th>Check-in</th><th>Score</th><th>Time</th><th>Status</th></tr>
{srows or '<tr><td colspan="5" class="muted">No sessions yet.</td></tr>'}</table>
<div class="muted" style="margin-top:6px">Tap a day to see every problem - what she got right and wrong.</div></div>"""

    body = f"""
<h1>Goldie's math progress</h1>
<div class="sub">Parent view - skills from Mrs. Derderian: times tables, 2x2-digit, 3x2-digit multiplication</div>
{statgrid}
{weak}
{skills_html}
{sess_html}
"""
    return PAGE.format(title="Goldie's progress", body=body)

def parent_session_page(con, sid):
    s = con.execute("SELECT day, started, finished, mood FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        return None
    done, right, first = session_stats(con, sid)
    probs = con.execute("""SELECT idx, skill, a, b, answer, goldie_answer, correct, first_try, attempts, seconds
                           FROM problems WHERE session_id=? ORDER BY idx""", (sid,)).fetchall()
    rows = ""
    for idx, skill, a, b, ans, gans, correct, ft, att, secs in probs:
        if correct is None:
            mark, gcell, tcell = '<span class="muted">-</span>', "-", "-"
        else:
            mark = '<span class="yes">&#10003;</span>' if correct else '<span class="no">&#10007;</span>'
            if correct and not ft:
                mark += ' <span class="muted">(2nd try)</span>'
            gcell = f"{gans:,}" if gans is not None else "-"
            if not correct:
                gcell = f'<span class="no">{gcell}</span> &rarr; <b>{ans:,}</b>'
            tcell = f"{secs:.0f}s" if secs is not None else "-"
        rows += (f"<tr><td>{a} &times; {b}</td><td class='muted'>{esc(SKILL_LABEL[skill])}</td>"
                 f"<td>{gcell}</td><td>{mark}</td><td>{tcell}</td></tr>")
    body = f"""
<h1>{fmt_day(s[0])} - {right} of {PROBLEMS_PER_DAY} right</h1>
<div class="sub">{first} on the first try &middot; <a href="/parent/{PARENT_TOKEN}">back to overview</a></div>
<div class="card"><table>
<tr><th>Problem</th><th>Skill</th><th>Her answer</th><th></th><th>Time</th></tr>
{rows}
</table></div>
<div class="card center">
<form method="post" action="/parent/{PARENT_TOKEN}/del_session/{sid}">
<button class="subbtn" style="background:#c0392b" type="submit">Delete this session's data</button>
</form>
<div class="muted" style="margin-top:6px">Removes this day from her history and stats (useful for test runs).</div>
</div>"""
    return PAGE.format(title=f"Session {fmt_day(s[0])}", body=body)



def wants(parts):
    return bool(parts) and parts[0] in ("g", "parent")

def do_get(h, parts, msg):
    con = db()
    try:
        if parts == ["g", GOLDIE_TOKEN]:
            h._send(200, goldie_home(con, msg))
        elif parts == ["g", GOLDIE_TOKEN, "play"]:
            page = play_page(con, msg)
            if page is None:
                h._redirect(f"/g/{GOLDIE_TOKEN}", "+All done - great work today!")
            else:
                h._send(200, page)
        elif parts == ["parent", PARENT_TOKEN]:
            h._send(200, parent_page(con))
        elif len(parts) == 4 and parts[0] == "parent" and parts[1] == PARENT_TOKEN and parts[2] == "session":
            try:
                sid = int(parts[3])
            except ValueError:
                sid = -1
            page = parent_session_page(con, sid)
            if page is None:
                h._send(404, "not found", "text/plain")
            else:
                h._send(200, page)
        else:
            h._send(404, "not found", "text/plain")
    finally:
        con.close()

def do_post(h, parts):
    con = db()
    try:
        if len(parts) == 3 and parts[0] == "g" and parts[1] == GOLDIE_TOKEN and parts[2] == "start":
            f = h._post_fields()
            s = get_or_create_session(con)
            mood = f.get("mood", "")
            if mood in ("great", "ok", "tired") and not s.get("mood"):
                con.execute("UPDATE sessions SET mood=? WHERE id=? AND mood IS NULL", (mood, s["id"]))
                con.commit()
            h._redirect(f"/g/{GOLDIE_TOKEN}/play")
        elif len(parts) == 3 and parts[0] == "g" and parts[1] == GOLDIE_TOKEN and parts[2] == "answer":
            f = h._post_fields()
            s = get_or_create_session(con)
            p = current_problem(con, s["id"])
            if p is None:
                h._redirect(f"/g/{GOLDIE_TOKEN}")
                return
            try:
                guess = int(f.get("answer", "").strip())
            except (ValueError, AttributeError):
                h._redirect(f"/g/{GOLDIE_TOKEN}/play", "!Type your answer as a number")
                return
            attempts = p["attempts"] + 1
            if guess == p["answer"]:
                row = con.execute("SELECT shown_at FROM problems WHERE id=?", (p["id"],)).fetchone()
                secs = max(0.0, (now_utc() - parse(row[0])).total_seconds()) if row and row[0] else None
                con.execute("""UPDATE problems SET goldie_answer=?, correct=1, first_try=?, attempts=?,
                               seconds=?, answered_at=? WHERE id=?""",
                            (guess, 1 if attempts == 1 else 0, attempts, secs, iso(now_utc()), p["id"]))
                con.commit()
                cheer = secrets.choice(CHEER if attempts == 1 else CHEER2)
                if finish_if_done(con, s["id"]):
                    h._redirect(f"/g/{GOLDIE_TOKEN}", "+All done - great work today!")
                else:
                    h._redirect(f"/g/{GOLDIE_TOKEN}/play", "+" + cheer)
            else:
                if attempts >= 2:
                    row = con.execute("SELECT shown_at FROM problems WHERE id=?", (p["id"],)).fetchone()
                    secs = max(0.0, (now_utc() - parse(row[0])).total_seconds()) if row and row[0] else None
                    con.execute("""UPDATE problems SET goldie_answer=?, correct=0, first_try=0, attempts=?,
                                   seconds=?, answered_at=? WHERE id=?""",
                                (guess, attempts, secs, iso(now_utc()), p["id"]))
                    con.commit()
                    h._redirect(f"/g/{GOLDIE_TOKEN}/play",
                                f"!This one was {p['answer']:,}. You'll get the next one!")
                else:
                    con.execute("UPDATE problems SET attempts=? WHERE id=?", (attempts, p["id"]))
                    con.commit()
                    h._redirect(f"/g/{GOLDIE_TOKEN}/play")
        elif len(parts) == 4 and parts[0] == "parent" and parts[1] == PARENT_TOKEN and parts[2] == "del_session":
            try:
                sid = int(parts[3])
            except ValueError:
                sid = -1
            con.execute("DELETE FROM problems WHERE session_id=?", (sid,))
            con.execute("DELETE FROM sessions WHERE id=?", (sid,))
            con.commit()
            h._redirect(f"/parent/{PARENT_TOKEN}", "Session deleted")
        else:
            h._send(404, "not found", "text/plain")
    finally:
        con.close()
