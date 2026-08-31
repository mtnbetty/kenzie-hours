#!/usr/bin/env python3
"""Tiny time tracker for Kenzie + Kristy. Stdlib-only (Python 3.10-3.12)."""
import os, io, json, sqlite3, secrets, cgi, mimetypes
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "hours.db")
TOKENS_PATH = os.path.join(DATA_DIR, "tokens.json")
TZ = ZoneInfo("America/Denver")
PORT = int(os.environ.get("PORT", "8080"))

os.makedirs(UPLOAD_DIR, exist_ok=True)

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS time_entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clock_in TEXT NOT NULL,
        clock_out TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS receipts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        note TEXT NOT NULL,
        filename TEXT NOT NULL)""")
    return con

def load_tokens():
    kt, bt = os.environ.get("KENZIE_TOKEN"), os.environ.get("BOSS_TOKEN")
    if kt and bt:
        return kt, bt
    if os.path.exists(TOKENS_PATH):
        t = json.load(open(TOKENS_PATH))
        return t["kenzie"], t["boss"]
    kt, bt = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    json.dump({"kenzie": kt, "boss": bt}, open(TOKENS_PATH, "w"))
    return kt, bt

KENZIE_TOKEN, BOSS_TOKEN = load_tokens()

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def parse(s):
    return datetime.fromisoformat(s)

def local(dt):
    return dt.astimezone(TZ)

def fmt_dt(dt):
    return local(dt).strftime("%a %b %-d, %-I:%M %p")

def fmt_day(dt):
    return local(dt).strftime("%a %b %-d")

def fmt_time(dt):
    return local(dt).strftime("%-I:%M %p")

def week_start(dt):
    d = local(dt).date()
    return d - timedelta(days=d.weekday())

def dur_str(seconds):
    seconds = int(seconds)
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m"

def money(cents):
    return f"${cents/100:,.2f}"

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f4f5f7; color: #1c1e21; padding: 16px; max-width: 560px; margin: 0 auto; }}
h1 {{ font-size: 1.35rem; margin: 8px 0 4px; }}
h2 {{ font-size: 1.05rem; margin: 24px 0 8px; color: #444; }}
.sub {{ color: #666; font-size: .9rem; margin-bottom: 16px; }}
.card {{ background: #fff; border-radius: 14px; padding: 18px; margin-bottom: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.bigbtn {{ display: block; width: 100%; border: 0; border-radius: 16px; padding: 30px 0;
  font-size: 1.5rem; font-weight: 700; color: #fff; cursor: pointer; }}
.in {{ background: #1faa55; }} .out {{ background: #e0483e; }}
.status {{ text-align: center; font-size: 1.05rem; margin-bottom: 14px; }}
.status b {{ font-weight: 700; }}
.timer {{ text-align: center; font-size: 2rem; font-weight: 700; margin: 6px 0 16px;
  font-variant-numeric: tabular-nums; }}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ text-align: left; padding: 7px 6px; border-bottom: 1px solid #eee; }}
th {{ color: #777; font-weight: 600; font-size: .8rem; text-transform: uppercase; }}
.totalrow td {{ font-weight: 700; border-bottom: none; }}
input[type=text], input[type=number] {{ width: 100%; padding: 14px; font-size: 1rem;
  border: 1px solid #ccc; border-radius: 10px; margin-bottom: 10px; }}
input[type=file] {{ width: 100%; padding: 12px 0; font-size: 1rem; }}
label {{ display: block; font-size: .85rem; color: #555; margin: 8px 0 4px; }}
.subbtn {{ display: block; width: 100%; border: 0; border-radius: 12px; padding: 16px 0;
  font-size: 1.1rem; font-weight: 600; color: #fff; background: #2f6fed; cursor: pointer; margin-top: 6px; }}
.thumb {{ width: 64px; height: 64px; object-fit: cover; border-radius: 8px; }}
.flash {{ background: #e7f6ec; color: #166b34; border-radius: 10px; padding: 12px;
  text-align: center; margin-bottom: 14px; font-weight: 600; }}
.err {{ background: #fdecea; color: #a32; }}
del {{ color: #999; }}
.delbtn {{ border: 0; background: none; color: #c00; font-size: 1rem; cursor: pointer; padding: 4px; }}
.muted {{ color: #888; font-size: .85rem; }}
.weekhead {{ background: #eceff3; font-weight: 700; }}
</style></head><body>
{body}
</body></html>"""

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def open_entry(con):
    return con.execute("SELECT id, clock_in FROM time_entries WHERE clock_out IS NULL ORDER BY id DESC LIMIT 1").fetchone()

def entries_with_durations(con):
    rows = con.execute("SELECT id, clock_in, clock_out FROM time_entries ORDER BY clock_in DESC").fetchall()
    out = []
    now = now_utc()
    for rid, ci, co in rows:
        ci_dt, co_dt = parse(ci), parse(co) if co else None
        secs = ((co_dt or now) - ci_dt).total_seconds()
        out.append({"id": rid, "in": ci_dt, "out": co_dt, "secs": secs, "open": co_dt is None})
    return out

def group_weeks(entries):
    weeks = {}
    for e in entries:
        ws = week_start(e["in"])
        weeks.setdefault(ws, []).append(e)
    return sorted(weeks.items(), key=lambda kv: kv[0], reverse=True)

TIMER_JS = """
<script>
(function(){
  var el = document.getElementById('elapsed');
  if(!el) return;
  var start = new Date(el.dataset.start).getTime();
  function tick(){
    var s = Math.max(0, Math.floor((Date.now()-start)/1000));
    var h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
    el.textContent = h + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
  }
  tick(); setInterval(tick, 1000);
})();
</script>"""

def kenzie_page(con, flash=None):
    kbase = "/k/" + KENZIE_TOKEN
    oe = open_entry(con)
    if oe:
        ci = parse(oe[1])
        status = f"You are <b>clocked in</b> since {fmt_time(ci)} ({fmt_day(ci)})"
        btn = f"""<form method="post" action="{kbase}/clock"><button class="bigbtn out" type="submit">Clock Out</button></form>"""
        timer = f'<div class="timer" id="elapsed" data-start="{oe[1]}"></div>' + TIMER_JS
    else:
        status = "You are <b>clocked out</b>"
        btn = f"""<form method="post" action="{kbase}/clock"><button class="bigbtn in" type="submit">Clock In</button></form>"""
        timer = ""
    fl = f'<div class="flash {"err" if flash and flash.startswith("!") else ""}">{esc(flash.lstrip("!"))}</div>' if flash else ""

    recent = entries_with_durations(con)[:7]
    rows = "".join(
        f"<tr><td>{fmt_day(e['in'])}</td><td>{fmt_time(e['in'])}</td>"
        f"<td>{fmt_time(e['out']) if e['out'] else '<b>now</b>'}</td><td>{dur_str(e['secs'])}</td></tr>"
        for e in recent)
    log = f"""<h2>Your recent shifts</h2><div class="card"><table>
      <tr><th>Day</th><th>In</th><th>Out</th><th>Time</th></tr>{rows or '<tr><td colspan=4 class="muted">No shifts yet</td></tr>'}
      </table></div>"""

    receipts = con.execute("SELECT created, amount_cents, note FROM receipts ORDER BY id DESC LIMIT 5").fetchall()
    rrows = "".join(f"<tr><td>{fmt_dt(parse(c))}</td><td>{money(a)}</td><td>{esc(n)}</td></tr>" for c, a, n in receipts)
    rlog = f"""<h2>Your recent receipts</h2><div class="card"><table>
      <tr><th>When</th><th>Amount</th><th>Note</th></tr>{rrows or '<tr><td colspan=3 class="muted">No receipts yet</td></tr>'}
      </table></div>"""

    body = f"""
<h1>Hi Kenzie</h1>
<div class="sub">Time tracker for your work with Mom</div>
{fl}
<div class="card">
  <div class="status">{status}</div>
  {timer}
  {btn}
</div>
<div class="card">
  <h2 style="margin-top:0">Submit a receipt</h2>
  <form method="post" action="{kbase}/receipt" enctype="multipart/form-data">
    <label for="photo">Receipt photo</label>
    <input id="photo" name="photo" type="file" accept="image/*" capture="environment" required>
    <label for="amount">Amount (USD)</label>
    <input id="amount" name="amount" type="number" step="0.01" min="0.01" inputmode="decimal" placeholder="12.50" required>
    <label for="note">What was it for?</label>
    <input id="note" name="note" type="text" maxlength="200" placeholder="Office supplies" required>
    <button class="subbtn" type="submit">Submit receipt</button>
  </form>
</div>
{log}
{rlog}
"""
    return PAGE.format(title="Clock In - Kenzie", body=body)

def boss_page(con, flash=None):
    bbase = "/boss/" + BOSS_TOKEN
    entries = entries_with_durations(con)
    weeks = group_weeks(entries)
    fl = f'<div class="flash {"err" if flash and flash.startswith("!") else ""}">{esc(flash.lstrip("!"))}</div>' if flash else ""

    oe = open_entry(con)
    status_html = ""
    if oe:
        ci = parse(oe[1])
        status_html = f"""<div class="card"><div class="status">Kenzie is <b>clocked in</b> right now (since {fmt_dt(ci)})</div>
        <div class="timer" id="elapsed" data-start="{oe[1]}"></div></div>""" + TIMER_JS

    wk_html = ""
    for ws, es in weeks:
        total = sum(e["secs"] for e in es)
        rows = ""
        for e in sorted(es, key=lambda x: x["in"]):
            out_cell = fmt_time(e["out"]) if e["out"] else "<b>still in</b>"
            rows += (f"<tr><td>{fmt_day(e['in'])}</td><td>{fmt_time(e['in'])}</td><td>{out_cell}</td>"
                     f"<td>{dur_str(e['secs'])}</td>"
                     f'<td><form method="post" action="{bbase}/del_entry" onsubmit="return confirm(\'Delete this shift?\')">'
                     f'<input type="hidden" name="id" value="{e["id"]}"><button class="delbtn" title="Delete">&#10005;</button></form></td></tr>')
        wk_html += f"""<div class="card"><table>
<tr class="weekhead"><td colspan="5">Week of {ws.strftime("%b %-d, %Y")}</td></tr>
<tr><th>Day</th><th>In</th><th>Out</th><th>Hours</th><th></th></tr>
{rows}
<tr class="totalrow"><td colspan="3">Total</td><td>{dur_str(total)}</td><td></td></tr>
</table></div>"""
    if not wk_html:
        wk_html = '<div class="card muted">No shifts logged yet.</div>'

    receipts = con.execute("SELECT id, created, amount_cents, note FROM receipts ORDER BY id DESC").fetchall()
    total_c = sum(r[2] for r in receipts)
    rrows = ""
    for rid, c, a, n in receipts:
        rrows += (f'<tr><td><a href="photo/{rid}" target="_blank"><img class="thumb" src="photo/{rid}" loading="lazy"></a></td>'
                  f"<td>{fmt_dt(parse(c))}</td><td>{money(a)}</td><td>{esc(n)}</td>"
                  f'<td><form method="post" action="{bbase}/del_receipt" onsubmit="return confirm(\'Delete this receipt?\')">'
                  f'<input type="hidden" name="id" value="{rid}"><button class="delbtn" title="Delete">&#10005;</button></form></td></tr>')
    if not rrows:
        rrows = '<tr><td colspan="5" class="muted">No receipts submitted yet.</td></tr>'

    body = f"""
<h1>Kristy - Kenzie's hours</h1>
<div class="sub">Employer view - refreshes each time you open it</div>
{fl}
{status_html}
<h2>Hours by week</h2>
{wk_html}
<h2>Receipts <span class="muted">(total {money(total_c)})</span></h2>
<div class="card"><table>
<tr><th>Photo</th><th>When</th><th>Amount</th><th>Note</th><th></th></tr>
{rrows}
</table></div>
"""
    return PAGE.format(title="Employer view", body=body)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, loc, flash=None):
        from urllib.parse import quote
        if flash:
            loc += ("&" if "?" in loc else "?") + "msg=" + quote(flash)
        self._send(303, b"", "text/plain", {"Location": loc})

    def _parts(self):
        return [p for p in urlparse(self.path).path.split("/") if p]

    def do_GET(self):
        parts = self._parts()
        q = urlparse(self.path).query
        msg = None
        if "msg=" in q:
            from urllib.parse import parse_qs
            msg = parse_qs(q).get("msg", [None])[0]
        con = db()
        try:
            if parts == ["healthz"]:
                self._send(200, "ok", "text/plain")
            elif parts == ["k", KENZIE_TOKEN]:
                self._send(200, kenzie_page(con, msg))
            elif parts == ["boss", BOSS_TOKEN]:
                self._send(200, boss_page(con, msg))
            elif len(parts) == 4 and parts[0] == "boss" and parts[1] == BOSS_TOKEN and parts[2] == "photo":
                rid = int(parts[3])
                row = con.execute("SELECT filename FROM receipts WHERE id=?", (rid,)).fetchone()
                if not row:
                    self._send(404, "not found", "text/plain")
                else:
                    path = os.path.join(UPLOAD_DIR, row[0])
                    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
                    with open(path, "rb") as f:
                        self._send(200, f.read(), ctype)
            else:
                self._send(404, "not found", "text/plain")
        finally:
            con.close()

    def do_POST(self):
        parts = self._parts()
        con = db()
        try:
            if len(parts) == 3 and parts[0] == "k" and parts[1] == KENZIE_TOKEN and parts[2] == "clock":
                oe = open_entry(con)
                if oe:
                    con.execute("UPDATE time_entries SET clock_out=? WHERE id=?", (iso(now_utc()), oe[0]))
                    msg = "Clocked out. Nice work!"
                else:
                    con.execute("INSERT INTO time_entries(clock_in) VALUES (?)", (iso(now_utc()),))
                    msg = "Clocked in - have a great shift!"
                con.commit()
                self._redirect(f"/k/{KENZIE_TOKEN}", msg)
            elif len(parts) == 3 and parts[0] == "k" and parts[1] == KENZIE_TOKEN and parts[2] == "receipt":
                ctype = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ctype:
                    self._redirect(f"/k/{KENZIE_TOKEN}", "!Upload failed - bad form data")
                    return
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                        environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype})
                try:
                    amount = float(form.getfirst("amount", "0"))
                except (ValueError, TypeError):
                    amount = 0
                note = (form.getfirst("note", "") or "").strip()
                fitem = form["photo"] if "photo" in form else None
                if amount <= 0 or not note or fitem is None or not getattr(fitem, "filename", ""):
                    self._redirect(f"/k/{KENZIE_TOKEN}", "!Need a photo, amount, and note")
                    return
                ext = os.path.splitext(fitem.filename)[1].lower() or ".jpg"
                fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}{ext}"
                data = fitem.file.read()
                if len(data) > 25 * 1024 * 1024:
                    self._redirect(f"/k/{KENZIE_TOKEN}", "!Photo too large (25MB max)")
                    return
                with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                    f.write(data)
                con.execute("INSERT INTO receipts(created, amount_cents, note, filename) VALUES (?,?,?,?)",
                            (iso(now_utc()), int(round(amount * 100)), note, fname))
                con.commit()
                self._redirect(f"/k/{KENZIE_TOKEN}", f"Receipt saved - {money(int(round(amount*100)))}")
            elif len(parts) == 3 and parts[0] == "boss" and parts[1] == BOSS_TOKEN and parts[2] in ("del_entry", "del_receipt"):
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln).decode()
                rid = int(body.split("id=")[1])
                if parts[2] == "del_entry":
                    con.execute("DELETE FROM time_entries WHERE id=?", (rid,))
                    con.commit()
                    self._redirect(f"/boss/{BOSS_TOKEN}", "Shift deleted")
                else:
                    row = con.execute("SELECT filename FROM receipts WHERE id=?", (rid,)).fetchone()
                    if row:
                        try:
                            os.remove(os.path.join(UPLOAD_DIR, row[0]))
                        except OSError:
                            pass
                        con.execute("DELETE FROM receipts WHERE id=?", (rid,))
                        con.commit()
                    self._redirect(f"/boss/{BOSS_TOKEN}", "Receipt deleted")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            self._send(500, f"error: {esc(e)}", "text/plain")
        finally:
            con.close()

if __name__ == "__main__":
    print(f"KENZIE_URL_PATH=/k/{KENZIE_TOKEN}")
    print(f"BOSS_URL_PATH=/boss/{BOSS_TOKEN}")
    print(f"listening on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
