# Add Tournaments

Turn tournament info (director emails, screenshots from SportsEngine / Bound / Midwest
Sports, PDFs, flyers) into rows on the private **Tournaments** tab.

Input files live in `inbox/tournaments/` (kept off GitHub). `$ARGUMENTS` may name a
single file or a URL instead.

---

## Rules

- **Facts only**: name, dates, venue, city, grades, gender, brackets, fees, deadline,
  links. Never copy descriptions, rules text, logos, or other wording from the source.
- Every tournament needs a `register_url` (official registration page) and a
  `source_url` (where the facts came from). Screenshots and emails don't carry a URL:
  if one isn't in the file or a `notes.txt` beside it, ask the user for it. For an
  email with no public page, `source_url` may be `email from <organizer>`, but
  `register_url` must still be a real link.
- Grades 3rd–8th only. Drop divisions outside that range and say so.
- Don't guess. If a date, fee, or grade range is unclear, ask.

---

## Step 1 — Find new files

List `inbox/tournaments/` (skip the `processed/` folder). Read each file with the Read
tool: `.txt` / `.eml` / `.pdf` / images. If `$ARGUMENTS` is a URL, fetch only that page.

## Step 2 — Extract one record per tournament

Fields (see `scripts/tournaments_tab.py` COLUMNS for the full list):

```
name, series, organizer, start_date, end_date (YYYY-MM-DD), venue, city, state (IA),
zip, gender (Boys | Girls | Both), grades (e.g. "3rd-8th" or "4th,5th,6th"),
brackets, entry_fee (number), entry_fee_notes, gate_fee_adult, gate_fee_student,
gate_fee_notes, registration_deadline (YYYY-MM-DD), register_url, source_url,
source_type (email | screenshot | website), tier (Local default), notes (private)
```

- `series` is the tournament's name without the year, so editions link across years.
- Check `city` against `data/ia_places.csv` (exact Census spelling, e.g. "Des Moines").
  If the city isn't there, ask.
- Leave `id` blank; it's generated from name + month.

## Step 3 — Review with the user

Show a compact table: name, dates, city, grades, gender, entry fee, gate fees,
deadline, register link. List anything missing or unclear and ask about it.

Ask: **"Add these N tournaments as drafts, or publish them now?"**

## Step 4 — Write to the Tournaments tab

Write the records to `inbox/tournaments/pending.json` (a JSON list), set `status` to
`draft` or `published` per the user's answer, then:

```bash
uv run python scripts/tournaments_tab.py add inbox/tournaments/pending.json
```

Show the dry run. On approval, re-run with `--commit`.

## Step 5 — Archive and sync

Move the processed files to `inbox/tournaments/processed/<today>/` and delete
`pending.json`. Then run the sync so published tournaments appear on the site:

```bash
uv run python scripts/sync.py
```

Confirm how many tournaments were added and which are live.
