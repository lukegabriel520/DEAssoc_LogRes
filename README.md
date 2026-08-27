# SCHEMA

**Scoring Candidates via Heuristic Evaluation Model Architecture (SCHEMA): A Bimodal Classification Pipeline** — live interview scoring for SBD tech-lead evaluations.

SCHEMA captures binary pass/fail flags per rubric question, computes a calibrated logistic **P(Pass)**, writes attribution notes, and syncs each department’s cohort to a shared **Google Sheet** in real time.

## Who this is for

| Role | Start here |
|------|------------|
| Org admin (you) | [docs/ADMIN_SETUP.md](docs/ADMIN_SETUP.md) |
| Tech lead / interviewer | [docs/INTERVIEWER_GUIDE.md](docs/INTERVIEWER_GUIDE.md) |
| Change questions/weights | [docs/CHANGE_RUBRIC.md](docs/CHANGE_RUBRIC.md) |
| Something broke | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## How it works (short)

1. Interviewer unlocks the app with the shared org password.
2. Picks a **department** (sheet tab name matches).
3. Checks Pass/Fail boxes while interviewing → live **P(Pass)** gauge.
4. Submit → row appended to that department’s Google Sheet tab + meta tabs; Top-K statuses recalculated.
5. Rubric edits save to Google (`_SCHEMA_RUBRICS`) so Streamlit Cloud redeploys do not wipe them.

## Scoring (expert-calibrated logit)

\[
z = \beta_0 + \sum_i w_i x_i,\quad P(\text{Pass}) = \sigma(\mathrm{clip}(z,-15,15))
\]

- Default \(\beta_0 = -2.0\) (~12% baseline with no positive signals).
- Top-K by \(P(\text{Pass})\); candidates below `pass_threshold_probability` cannot receive **Top-K Pass**.

## Local run (dev)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# edit secrets.toml — password, spreadsheet_id, service account JSON fields
streamlit run app.py
```

## Streamlit Cloud (pitch path)

1. Push this repo to GitHub (secrets are gitignored).
2. [share.streamlit.io](https://share.streamlit.io) → New app → `app.py`.
3. Paste secrets (same keys as the example file).
4. Share your Google Sheet with the service account **client_email** as Editor.

Details: [docs/ADMIN_SETUP.md](docs/ADMIN_SETUP.md).

## Departments

AI - Automation · AI - Machine Learning · Cloud and Infrastructure · Cybersecurity · Data Engineering · Game Development · IoT & Robotics · Project Management · Software Engineering · UI/UX

## Repo map

- `app.py` — Streamlit UI
- `config/` — department registry + default rubrics
- `core/` — scoring, Sheets store, export
- `docs/` — role-based guides
