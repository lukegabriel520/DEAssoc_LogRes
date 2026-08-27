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
- Master layout tab missing (`Sheet1` or your `template_tab` in secrets).
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

The current layout uses four header rows:

1. Spacer
2. Date banner
3. `INTERVIEW TIME | NAME | POSITION APPLICATIONS | Meeting Link | Notes | STATUS`
4. `1st Choice | 2nd Choice` under `POSITION APPLICATIONS`

Latest builds insert missing header rows above existing content automatically and do not overwrite candidate rows. If an old header is duplicated below row 4, remove only that old header block manually; keep all candidate rows. Then submit a new test candidate.

## Candidate was added in the wrong row

Latest builds append through the table range `A4:G`, so formatting on empty rows does not affect placement. Confirm the app is current, the department tab has the four-row header above, and `template_tab` points to the intended master tab.

## Google Sheets 429 / Quota exceeded

**Cause:** Too many read requests (often from rapid checkbox toggles before caching was added).

**Fix:** Restart the app (latest code caches reads). Wait 1 minute if quota was hit, then submit again.

If it persists: avoid opening Cohort and Interview in rapid alternation; use **Refresh** on Cohort only when needed.

## `_SCHEMA_FEATURES` / `_SCHEMA_RUBRICS` tabs empty (no headers)

**Cause:** Older builds used the wrong gspread 6 `update()` argument order, so meta-tab headers were never written.

**Fix:** Update to the latest code and restart Streamlit. Open the app once — it will stamp row 1 automatically. If tabs still look wrong, delete `_SCHEMA_FEATURES` and `_SCHEMA_RUBRICS`, refresh the app, and headers should reappear.

## FALLBACK banner on the gauge

Weights are invalid or missing. Open Rubric Manager, ensure every weight > 0, Save, Rescore.
