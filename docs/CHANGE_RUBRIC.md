# Change a rubric (layman steps)

You can edit interview questions and weights without touching code.

## Important ideas

- Each **department** has its own rubric.
- Saving in the app writes to Google Sheets tab `_SCHEMA_RUBRICS`. That survives Streamlit Cloud restarts.
- Files under `config/rubrics/` are **defaults** if Google has no override yet.
- Question **id** values (like `d2_systems_logic`) should stay stable once you have candidates. Renaming ids breaks rescoring history.

## Change one question’s wording

1. Unlock SCHEMA → pick your department.
2. Open the **Rubric Manager** tab.
3. Scroll to the question card.
4. Edit **Prompt**, **Pass criteria**, and/or **Fail criteria**.
5. Click **Validate form draft** (optional sanity check).
6. Click **Save to Google Sheets**.
7. You should see: *Saved to Google (`_SCHEMA_RUBRICS`). Survives redeploy.*

## Change a weight

1. Same place — edit the **Weight** number (must be greater than 0).
2. Higher weight = stronger push on P(Pass) when checked.
3. Save to Google Sheets.
4. If candidates already exist, click **Rescore all candidates** so old rows use the new weights.

## Change Top-K or baseline difficulty

Under **Model parameters**:

- `beta_0` — more negative = stricter baseline (harder to pass with few checks).
- `top_k_slots` — how many Top-K Pass seats.
- `pass_threshold_probability` — minimum P(Pass) required to earn Top-K Pass.

Save after edits. Use **Rescore** / **Re-rank** if a cohort already exists.

## Advanced JSON

Only if you are comfortable with JSON:

1. Expand **Advanced JSON**.
2. Edit carefully.
3. Click **Validate JSON into draft**.
4. Then **Save to Google Sheets**.

If validation fails, fix the error text shown — do not save broken JSON.

## What not to do

- Don’t delete a question id that already appears on past candidates unless you accept broken history.
- Don’t set any weight to 0 or negative (app will reject or fall back).
- Don’t edit the Google Sheet rubric JSON by hand unless you know the schema.

## Need a brand-new question?

Ask the admin to add it in the Rubric Manager (or JSON) with a **new unique id**, then Save. Prefer adding over recycling old ids.
