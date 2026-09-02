# kenzie-hours (+ goldie-math)

Single Render web service hosting two small stdlib-only apps (Python 3.10-3.12, no dependencies):

**Family hub** (`app.py`)
- One landing page linking to each kid's app: `/family/<FAMILY_TOKEN>`

**Kenzie time tracker** (`app.py`)
- Kenzie's clock in/out + receipt upload: `/k/<KENZIE_TOKEN>`
- Kristy's employer view: `/boss/<BOSS_TOKEN>`

**Goldie math practice** (`math_app.py`, served by the same process)
- Goldie's daily mission (22 problems, ~20 min; times tables, 2x2-digit, 3x2-digit): `/g/<GOLDIE_TOKEN>`
- Kristy's parent view (per-problem results, weak spots, accuracy by skill): `/parent/<PARENT_TOKEN>`

- Env vars: `PORT` (Render sets it), `DATA_DIR` (persistent disk mount), `KENZIE_TOKEN`, `BOSS_TOKEN`, `FAMILY_TOKEN`, `GOLDIE_TOKEN`, `PARENT_TOKEN` (set in Render dashboard, never in this repo)
- Data (SQLite: `hours.db` + `math.db`, receipt photos) lives in `$DATA_DIR` on the shared persistent disk
- Deploys: pushes to `main` auto-deploy on Render via the Render GitHub App
