# Import Weekend Scores

Import basketball scores from screenshots or PDFs in `/inbox/$ARGUMENTS/`.

The argument is the Saturday date of the weekend, e.g. `/import-weekend 2026-11-08`.

---

## Step 1 — Discover event subfolders

List the contents of `/inbox/$ARGUMENTS/`. Each subdirectory is one event — its folder
name is the event name. Screenshots sit inside their event's subfolder.

For each event subfolder, read its `notes.txt` if present. Notes may supply or override:
event tier (National / Regional / Local), bracket level (Gold / Silver), age group,
gender, season. Notes apply only to that event's games.

Default values when not specified anywhere:
- Event Tier: `Local`
- Bracket Level: `Silver`

---

## Step 2 — Extract games from each screenshot

For each event subfolder, list every image or PDF file (.png, .jpg, .jpeg, .PNG, .JPG,
.HEIC, .pdf, .PDF) inside it. Use the folder name as the `event_name` for all games in
that subfolder.

For each file, use the Read tool to view it (for PDFs over 10 pages, read in page
ranges), then extract every **completed game** (final scores only). Skip: scheduled
games, forfeits (unless clearly marked as completed), in-progress games.

**Grade and gender from filename**: the filename encodes the grade and gender
for all teams in that file — e.g. `8th girls.png` means every team in that screenshot
is 8th-grade Girls. Mixed brackets (`5th:6th Boys.png`) hold teams from both grades.

**Whole-tournament files** (one PDF or screenshot covering several grades): take each
game's grade and gender from the division heading it sits under in the file, and set
`source_screenshot` to `"<Event Name>/<grade> <gender>"` (e.g.
`"Fall Frenzy 2026/6th boys"`) so later steps can read the grade. If a game's division
isn't clear, ask the user rather than guessing.

**One name per club and grade**: the site groups games by team name. If the same team
name shows up in more than one grade in this batch, append the grade
(`Unite` → `Unite 4th`, `Unite 6th`) unless the user says it's one team playing up.

For each completed game, record:
```
game_date       YYYY-MM-DD
home_team       team name exactly as shown
away_team       team name exactly as shown
home_score      integer string, or "?" if unreadable
away_score      integer string, or "?" if unreadable
event_name      tournament / event name
event_tier      National | Regional | Local  (from notes or default)
bracket_level   Gold | Silver               (from notes or default)
season          e.g. "Fall 2026"
source_screenshot  relative path from inbox/YYYY-MM-DD (e.g. "Event Name/photo.png")
```

Apply any overrides from notes.txt. If a score digit is unclear, use "?" — do not guess.

---

## Step 3 — Write extracted-games.json

Write all extracted games to `/inbox/$ARGUMENTS/extracted-games.json`:

```json
[
  {
    "season": "Fall 2026",
    "game_date": "2026-11-08",
    "home_team": "Exact Team Name From Screenshot",
    "away_team": "Exact Team Name From Screenshot",
    "home_score": "42",
    "away_score": "38",
    "event_name": "Tournament Name",
    "event_tier": "Local",
    "bracket_level": "Silver",
    "source_screenshot": "photo1.jpg"
  }
]
```

---

## Step 4 — Run the check step

```bash
uv run python scripts/import_weekend.py check $ARGUMENTS
```

This matches team names, deduplicates within the batch and against the Games sheet,
and writes `/inbox/$ARGUMENTS/staging.csv`.

---

## Step 4b — Register new teams (if any are unmatched)

Before resolving flags, run the new-team detection step:

```bash
uv run python scripts/import_weekend.py add-teams $ARGUMENTS
```

This reads `extracted-games.json`, finds every team not yet in the Teams sheet, and
infers their **grade and gender from the screenshot filename** (e.g. `8th girls.png` →
8th, Girls). For mixed-grade brackets it also reads grade from team names
(e.g. "Kingdom Hoops 7th Navy" → 7th).

Show the output to the user. If new teams are listed:

1. Ask: "Ready to add these N teams to the Teams sheet?"
2. On approval, run:
   ```bash
   uv run python scripts/import_weekend.py add-teams $ARGUMENTS --commit
   ```
3. Any team still showing `?` for grade or gender needs the user to fill it in the
   Teams sheet manually (provide the link).
4. Re-run Step 4 (`check`) so staging.csv reflects the newly registered teams.

---

## Step 5 — Resolve remaining flags with the user

Present the full `check` output. For any **still-unmatched team** (shouldn't be many
after add-teams), show candidates and ask:

> "'{raw name}' didn't match any team. Candidates: A, B, C — which is correct, or is
> this a new team? (type the number, the name, or 'new')"

When the user picks a match, save the alias:
```bash
uv run python scripts/import_weekend.py alias add "<raw name>" "<canonical name>"
```

After all flags are resolved, re-run the check step so staging.csv is updated with the
confirmed matches.

---

## Step 6 — Approval gate

Show the final counts (ready / flagged) and ask:

> "Ready to import N games to the Google Sheets Games sheet. Approve?"

**Do not run the import step until the user explicitly approves.**

If they want to edit staging.csv by hand first, wait for them to do so, then proceed.

---

## Step 7 — Import

```bash
uv run python scripts/import_weekend.py import $ARGUMENTS
```

This appends approved rows to the Games sheet, writes a log entry to
`/inbox/import_log.md`, and moves the folder to `/inbox/processed/$ARGUMENTS/`.

Rankings update automatically on the next page load — no extra step needed.

---

## Step 8 — Done

Confirm: how many games were imported, which events, and that the folder was archived.

---

## Corrections after import

The site groups games by team **name**, so each club+grade needs its own name
(e.g. `Unite 4th`). A team that played up in a higher bracket can end up under the
wrong grade. Both tools dry-run by default; add `--commit` to write.

- **Split team is really one team** (e.g. 6th-grade team also listed as `X 7th`):
  ```bash
  uv run python scripts/merge_team.py "515 Hoops 7th" "515 Hoops 6th"
  ```
  Moves every game to the second name and deletes the first from Teams.
- **Team is listed under the wrong grade** and has no row at its real grade:
  ```bash
  uv run python scripts/regrade_team.py "Chaos Black 7th" "Chaos Black 6th" 6th
  ```
  Renames the team and its games and sets its Age Group.
