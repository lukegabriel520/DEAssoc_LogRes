# Interviewer guide

## Before the session

1. Open the SCHEMA app URL your admin shared.
2. If the page spins a long time, wait — free Streamlit apps sleep when idle. Give it 1–2 minutes, then refresh.
3. Enter the **shared org password**.
4. Select **your department** (example: Data Engineering). The Google Sheet tab uses this same name.

## Live interview

1. Confirm the auto **Candidate #** label in the blue info box.
2. Fill **Full Name** (required).
3. Fill **1st Choice** / **2nd Choice** (applicant’s track preferences).
4. Paste **Meeting Link** if you have one (invalid/empty becomes `N/A`).
5. For each question card:
   - Read the prompt aloud.
   - Use the muted Pass / Fail text as your rubric.
   - Check **Criterion met (Pass)** only when they meet the pass bar.
6. Watch the right-hand **P(Pass)** gauge update as you check boxes.
7. Add short qualitative notes if useful.
8. Click **Submit & Ingest Candidate**.
   - Success = row written to Google Sheets and form clears.
   - Error = form stays filled; tell admin or see Troubleshooting.

## What STATUS means

| STATUS | Meaning |
|--------|---------|
| Top-K Pass | Ranked in the Top-K slots **and** above the probability threshold |
| Review | Borderline (next ranks after Top-K, or Top-K rank but under threshold) |
| Fail | Below the review band |

Top-K can be adjusted on the **Cohort Ranking** tab.

## Cohort Ranking tab

- See everyone already submitted for **your department**, sorted by score.
- Move the **Top-K** slider if slot count changes mid-day.
- Download `.xlsx` or `.csv` for offline backup.

## Switching department

Sidebar → **Switch department** → pick another track.  
Only do this when you are sure — each department has its own sheet tab and rubric.

## Do / Don’t

- Do open the app a few minutes early.
- Do submit only after the interview for that person is done.
- Don’t pick another department “to peek” unless you intend to write there.
- Don’t share the org password outside the lead group.
