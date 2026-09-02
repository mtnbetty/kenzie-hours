# kenzie-hours (+ goldie-math + josie-math + reading)

Single Render web service hosting the family hub and small stdlib-only apps (Python 3.10-3.12, no dependencies):

**Family hub** (`app.py`)
- One landing page linking to each kid's app: `/family/<FAMILY_TOKEN>`

**Kenzie time tracker** (`app.py`)
- Kenzie's clock in/out + receipt upload: `/k/<KENZIE_TOKEN>`

**Goldie math practice** (`math_app.py`, served by the same process)
- Goldie's daily mission (22 problems, ~20 min; times tables, 2x2-digit, 3x2-digit): `/g/<GOLDIE_TOKEN>`
- Daily 30-min reading check-off on her tab

**Josie math practice** (`josie_app.py`, served by the same process)
- Josie's daily set (15 problems, ~20 min; one/two-step equations, exponents, fractions, percents, slope, order of operations; difficulty scales with accuracy): `/j/<JOSIE_TOKEN>`
- Daily 30-min reading check-off on her tab

**Reading tracker** (`reading_app.py`)
- Shared reading check-offs + streaks for both girls (SQLite `reading.db`)

**Unified parent dashboard** (`app.py`)
- One page with Kenzie's hours/receipts, both girls' reading check-offs, and both math apps' results.
- Served at BOTH `/boss/<BOSS_TOKEN>` and `/parent/<PARENT_TOKEN>` (old saved links keep working).
- Per-day math detail: `/parent/<PARENT_TOKEN>/session/<id>` (Goldie), `/parent/<PARENT_TOKEN>/jsession/<id>` (Josie)

- Env vars: `PORT` (Render sets it), `DATA_DIR` (persistent disk mount), `KENZIE_TOKEN`, `BOSS_TOKEN`, `FAMILY_TOKEN`, `GOLDIE_TOKEN`, `PARENT_TOKEN`, `JOSIE_TOKEN` (set in Render dashboard or generated onto the disk, never in this repo)
- Data (SQLite: `hours.db` + `math.db` + `josie.db` + `reading.db`, receipt photos) lives in `$DATA_DIR` on the shared persistent disk
- Deploys: pushes to `main` auto-deploy on Render via the Render GitHub App
