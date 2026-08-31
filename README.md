# kenzie-hours

Single-file, stdlib-only Python time tracker (Python 3.10-3.12, no dependencies).

- Kenzie's clock in/out + receipt upload: `/k/<KENZIE_TOKEN>`
- Kristy's employer view: `/boss/<BOSS_TOKEN>`
- Env vars: `PORT` (Render sets it), `DATA_DIR` (persistent disk mount), `KENZIE_TOKEN`, `BOSS_TOKEN` (set in Render dashboard, never in this repo)
- Data (SQLite + receipt photos) lives in `$DATA_DIR` on the persistent disk
- Deploys: pushes to `main` auto-deploy on Render (`autoDeploy: true` in render.yaml)
