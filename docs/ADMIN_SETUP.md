# Admin setup (one-time)

You configure Google + Streamlit secrets once. Interviewers only open the URL and pick a department.

## 1. Google Cloud service account

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable **Google Sheets API** and **Google Drive API**.
4. **IAM & Admin → Service Accounts → Create**.
5. Create a key → JSON → download the file (keep it private).
6. Copy the `client_email` from that JSON (looks like `name@project.iam.gserviceaccount.com`).

## 2. Share your Google Sheet

1. Open your master spreadsheet (test copy is fine).
2. Click **Share**.
3. Paste the service account `client_email`.
4. Role: **Editor**.
5. Uncheck “Notify people” if offered → Share.
6. Copy the Spreadsheet ID from the URL:

`https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit`

SCHEMA will add `_SCHEMA_FEATURES` + `_SCHEMA_RUBRICS` meta tabs and build department tabs by **duplicating your master layout tab** (`Sheet1` by default — see section 3).

## 3. Streamlit Community Cloud

1. Push this repository to GitHub (**do not** commit `secrets.toml` or the JSON key).
2. Go to [https://share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. **New app** → select the repo → main file `app.py` → Deploy.
4. **Settings → Secrets** → paste TOML like `.streamlit/secrets.toml.example`:
   - `app_password` — shared password for all leads
   - `spreadsheet_id` — from step 2
   - `[google_service_account]` — every field from the JSON key file  
     Keep `\n` inside `private_key` as escaped newlines.
5. Save secrets → reboot the app if prompted.

Format **`Sheet1`** (or another tab — set `template_tab` in secrets) with your interview header layout. SCHEMA **duplicates that tab** on first submit for each department (e.g. **Data Engineering**) and appends candidate rows below the header block.

To refresh a department tab: delete it in Google Sheets and submit again — it will be recreated from the master tab. Edit **Sheet1** to change formatting for all future department tabs.

## 4. Smoke test

1. Open the Cloud URL (first load may take ~30–60s if the app was asleep).
2. Enter `app_password`.
3. Choose **Data Engineering**.
4. Submit a dummy candidate with a few boxes checked.
5. Confirm a new row on the **Data Engineering** tab and rows on `_SCHEMA_FEATURES`.

## 5. Rotate password later

Change `app_password` in Streamlit Cloud Secrets → Save → tell leads the new password.

## 6. Local admin testing

```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# fill values
streamlit run app.py
```

## Security notes

- Only you hold the service account key (in Cloud Secrets).
- Anyone with the app URL + password can write to any department tab — treat the password like a door code.
- Never commit secrets to git.
