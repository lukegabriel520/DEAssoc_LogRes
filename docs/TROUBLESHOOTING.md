# Troubleshooting

## App takes forever to open

**Cause:** Streamlit Community Cloud sleeps free apps when idle.

**Fix:** Wait 30–90 seconds, refresh once. Open the URL a few minutes before interviews start.

## “Incorrect password”

**Fix:** Ask admin for the current `app_password`. Admin can rotate it in Streamlit Cloud → Settings → Secrets.

## “Streamlit secrets missing” / Google not connected

**Fix (admin):**

1. Confirm Secrets include `app_password`, `spreadsheet_id`, and `[google_service_account]`.
2. Confirm the Sheet is shared with the service account **client_email** as Editor.
3. Confirm Sheets API + Drive API are enabled on the GCP project.
4. Reboot the Cloud app after changing secrets.

## Submit failed — form kept

Your interview answers are still on screen. Common causes:

- Sheet not shared with the service account.
- Wrong `spreadsheet_id`.
- Network blip / API quota.

**Fix:** Admin checks sharing + secrets. Interviewer clicks Submit again (do not retype unless the form cleared).

## I wrote to the wrong department

Rows land on the tab you selected at the gate.

**Fix:** Manually move/delete the bad row in Google Sheets (department tab + matching row on `_SCHEMA_FEATURES` if present). Re-rank from Cohort tab afterward.

## STATUS looks wrong after Top-K change

**Fix:** Cohort Ranking → set slider → **Re-rank STATUS now**.

## Rubric changes disappeared after redeploy

That happens only if you edited git files and never clicked **Save to Google Sheets**.

**Fix:** Edit in Rubric Manager → **Save to Google Sheets**. Overrides live in `_SCHEMA_RUBRICS`.

## Header looks duplicated on a sheet

**Fix (admin):** Open the tab, delete extra header rows so row 1–2 match:

`INTERVIEW TIME | NAME | POSITION APPLICATIONS | Meeting Link | Notes | STATUS`  
with `1st Choice | 2nd Choice` under POSITION APPLICATIONS.

Then submit a new test row.

## FALLBACK banner on the gauge

Weights are invalid or missing. Open Rubric Manager, ensure every weight &gt; 0, Save, Rescore.
