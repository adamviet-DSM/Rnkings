#!/usr/bin/env python3
"""
Team Ranker — weekly screenshot import helper.

Usage:
  uv run python scripts/import_weekend.py check      YYYY-MM-DD
  uv run python scripts/import_weekend.py import     YYYY-MM-DD
  uv run python scripts/import_weekend.py add-teams  YYYY-MM-DD [--commit]
  uv run python scripts/import_weekend.py alias add "<alias>" "<canonical>"
  uv run python scripts/import_weekend.py alias list
"""

import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
INBOX = ROOT / "inbox"
PROCESSED = INBOX / "processed"
ALIASES_FILE = ROOT / "aliases.json"
LOG_FILE = INBOX / "import_log.md"

# Must match Games sheet header row exactly
GAMES_COLUMNS = [
    "Season", "Home Team Name", "Away Team Name",
    "Home Score", "Away Score", "Game Date",
    "Event Name", "Event Tier", "Bracket Level",
]
STAGING_COLUMNS = GAMES_COLUMNS + ["Source Screenshot", "_status"]


# ── Grade / gender helpers ───────────────────────────────────────────────────

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n: int) -> str:
    return f"{n}{_ORDINAL_SUFFIX.get(n, 'th')}"


def parse_grade_gender_from_path(path: str) -> tuple:
    """
    Extract grade and gender from a screenshot filename like '8th girls.png'.
    Returns (grade, gender).  Either value is None when ambiguous.
    Mixed brackets ('5th:6th Boys.png') return (None, gender).
    """
    fname = Path(path).name.lower()
    # Gender
    if re.search(r"\bgirl", fname):
        gender = "Girls"
    elif re.search(r"\bboy", fname):
        gender = "Boys"
    else:
        gender = None

    # Ordinals in filename, e.g. "8th", "7th grade", "5th:6th"
    grades = re.findall(r"\b(\d+)(?:st|nd|rd|th)\b", fname)
    if len(grades) == 1:
        grade = _ordinal(int(grades[0]))
    else:
        grade = None  # 0 or multiple grades → ambiguous

    return grade, gender


def infer_grade_from_name(team_name: str) -> str | None:
    """Try to infer grade from the team name itself, e.g. 'Kingdom Hoops 7th Navy' → '7th'."""
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", team_name, re.IGNORECASE)
    if m:
        return _ordinal(int(m.group(1)))
    return None


# ── Alias helpers ────────────────────────────────────────────────────────────

def load_aliases() -> dict:
    if ALIASES_FILE.exists():
        return json.loads(ALIASES_FILE.read_text())
    return {}


def save_aliases(aliases: dict) -> None:
    ALIASES_FILE.write_text(json.dumps(aliases, indent=2, sort_keys=True))


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, normalize age suffixes."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    # 14U / 14 U / 14u → 14u
    text = re.sub(r"\b(\d+)\s*u\b", r"\1u", text, flags=re.IGNORECASE)
    # "4th grade" → "4th"
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\s+grade\b", r"\1th", text, flags=re.IGNORECASE)
    return text


# ── Team matching ────────────────────────────────────────────────────────────

def match_team(raw: str, known: list, aliases: dict) -> tuple:
    """
    Returns (matched_name_or_None, match_type, candidates).
    match_type: "exact" | "alias" | "normalized" | "none"
    """
    raw = raw.strip()

    # 1. Exact
    if raw in known:
        return raw, "exact", []

    # 2. Alias
    norm = normalize(raw)
    if norm in aliases and aliases[norm] in known:
        return aliases[norm], "alias", []

    # 3. Normalized against known teams
    norm_map = {normalize(t): t for t in known}
    if norm in norm_map:
        return norm_map[norm], "normalized", []

    # 4. Token-overlap candidates
    raw_tokens = set(norm.split())
    scored = []
    for t in known:
        t_tokens = set(normalize(t).split())
        union = raw_tokens | t_tokens
        overlap = len(raw_tokens & t_tokens) / len(union) if union else 0
        if overlap > 0.35:
            scored.append((overlap, t))
    scored.sort(reverse=True)
    return None, "none", [t for _, t in scored[:3]]


# ── Sheet helpers ────────────────────────────────────────────────────────────

def _sys_path_insert():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def get_known_teams() -> list:
    _sys_path_insert()
    from sheets import get_teams
    rows = get_teams()
    return [str(r.get("Team Name", "")).strip() for r in rows if r.get("Team Name")]


def get_teams_full() -> list:
    _sys_path_insert()
    from sheets import get_teams
    return get_teams()


def get_existing_games() -> list:
    _sys_path_insert()
    from sheets import get_games
    return get_games()


def game_key(game: dict) -> tuple:
    return (
        str(game.get("Game Date", "")).strip(),
        normalize(str(game.get("Home Team Name", ""))),
        normalize(str(game.get("Away Team Name", ""))),
        str(game.get("Home Score", "")).strip(),
        str(game.get("Away Score", "")).strip(),
    )


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_check(folder_date: str) -> None:
    folder = INBOX / folder_date
    if not folder.exists():
        sys.exit(f"ERROR: {folder} does not exist.")

    extracted_file = folder / "extracted-games.json"
    if not extracted_file.exists():
        sys.exit(f"ERROR: {extracted_file} not found. Run the extraction step first.")

    # Report subfolder structure found
    event_dirs = [d for d in folder.iterdir() if d.is_dir() and d.name != "processed"]
    if event_dirs:
        print(f"Events found: {', '.join(d.name for d in sorted(event_dirs))}")

    extracted = json.loads(extracted_file.read_text())
    aliases = load_aliases()

    print("Fetching teams from Google Sheets…")
    try:
        known = get_known_teams()
    except Exception as e:
        sys.exit(f"ERROR fetching teams: {e}")

    print("Fetching existing games for dedup…")
    try:
        existing = get_existing_games()
    except Exception as e:
        sys.exit(f"ERROR fetching games: {e}")

    existing_keys = {game_key(g) for g in existing}
    seen_in_batch = set()
    ready = []
    flags = []

    for g in extracted:
        issues = []

        home_raw = str(g.get("home_team", "")).strip()
        away_raw = str(g.get("away_team", "")).strip()
        home_matched, home_type, home_cands = match_team(home_raw, known, aliases)
        away_matched, away_type, away_cands = match_team(away_raw, known, aliases)

        if home_type == "none":
            cand_str = f" — candidates: {home_cands}" if home_cands else " — no candidates"
            issues.append(f"Unmatched home team: '{home_raw}'{cand_str}")
        if away_type == "none":
            cand_str = f" — candidates: {away_cands}" if away_cands else " — no candidates"
            issues.append(f"Unmatched away team: '{away_raw}'{cand_str}")

        home_score = str(g.get("home_score", "")).strip()
        away_score = str(g.get("away_score", "")).strip()
        if not home_score.isdigit() or not away_score.isdigit():
            issues.append(f"Unclear score: '{home_score}' vs '{away_score}'")

        if not g.get("game_date"):
            issues.append("Missing: game_date")
        # Season = the Fall–Summer cycle ('2026-27'), from the game date when possible
        _sys_path_insert()
        from ranking import cycle_for_date, season_cycle
        season = cycle_for_date(str(g.get("game_date", ""))) or season_cycle(str(g.get("season", "")))
        if not season:
            issues.append("Missing: season")

        row = {
            "Season": season,
            "Home Team Name": home_matched or home_raw,
            "Away Team Name": away_matched or away_raw,
            "Home Score": home_score,
            "Away Score": away_score,
            "Game Date": g.get("game_date", ""),
            "Event Name": g.get("event_name", ""),
            "Event Tier": g.get("event_tier", "Local"),
            "Bracket Level": g.get("bracket_level", "Silver"),
            "Source Screenshot": g.get("source_screenshot", ""),
            "_status": "READY",
        }

        bkey = game_key(row)
        if bkey in seen_in_batch:
            issues.append("Duplicate within batch")
        else:
            seen_in_batch.add(bkey)

        if bkey in existing_keys:
            issues.append("Already in Games sheet — will be skipped")

        if issues:
            row["_status"] = "FLAGGED"
            flags.append({"game": row, "issues": issues})
        else:
            ready.append(row)

    # Write staging.csv
    staging = folder / "staging.csv"
    all_rows = ready + [f["game"] for f in flags]
    with open(staging, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=STAGING_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    # Print review
    n_screenshots = len({g.get("source_screenshot", "") for g in extracted if g.get("source_screenshot")})
    print(f"\n{'='*62}")
    print(f"REVIEW — {folder_date}")
    print(f"{'='*62}")
    print(f"  Screenshots : {n_screenshots}")
    print(f"  Games found : {len(extracted)}")
    print(f"  Ready       : {len(ready)}")
    print(f"  Flagged     : {len(flags)}")

    if ready:
        print(f"\n{'─'*62}")
        print("READY TO IMPORT")
        print(f"{'─'*62}")
        fmt = "{:<11}  {:<22} {:>3}–{:<3}  {:<22}  {}"
        print(fmt.format("Date", "Home Team", "H", "A", "Away Team", "Event"))
        for r in ready:
            print(fmt.format(
                r["Game Date"][:10],
                r["Home Team Name"][:22],
                r["Home Score"],
                r["Away Score"],
                r["Away Team Name"][:22],
                r["Event Name"][:28],
            ))

    if flags:
        print(f"\n{'─'*62}")
        print("FLAGGED (not imported until resolved)")
        print(f"{'─'*62}")
        for i, item in enumerate(flags, 1):
            g = item["game"]
            print(f"\n[{i}] {g['Home Team Name']} {g['Home Score']}–{g['Away Score']} "
                  f"{g['Away Team Name']}  ({g['Game Date']})")
            for issue in item["issues"]:
                print(f"     ⚠  {issue}")

    print(f"\nStaging file: {staging}")
    print("Edit staging.csv to fix flags, change _status to READY, then approve.")


def cmd_import(folder_date: str) -> None:
    folder = INBOX / folder_date
    staging = folder / "staging.csv"

    if not staging.exists():
        sys.exit(f"ERROR: {staging} not found. Run 'check' first.")

    rows_to_import = []
    with open(staging, newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("_status", "").upper() == "READY":
                rows_to_import.append({col: row.get(col, "") for col in GAMES_COLUMNS})

    if not rows_to_import:
        print("No READY rows in staging.csv — nothing to import.")
        return

    print(f"Importing {len(rows_to_import)} games to Google Sheets…")

    _sys_path_insert()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.getenv("GAMES_SHEET_ID")
    if not creds_json:
        sys.exit("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
    if not sheet_id:
        sys.exit("ERROR: GAMES_SHEET_ID not set in .env")

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(sheet_id).get_worksheet(0)

    headers = ws.row_values(1)
    if not headers:
        sys.exit("ERROR: Games sheet has no header row.")

    all_rows = [[row.get(h, "") for h in headers] for row in rows_to_import]
    ws.append_rows(all_rows, value_input_option="USER_ENTERED")

    print(f"✓  {len(rows_to_import)} rows appended to Games sheet.")

    # Log
    events = ", ".join(sorted({r["Event Name"] for r in rows_to_import if r["Event Name"]})) or "—"
    log_entry = (
        f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M')} — {folder_date}\n"
        f"- Games imported: {len(rows_to_import)}\n"
        f"- Events: {events}\n"
    )
    with open(LOG_FILE, "a") as fh:
        fh.write(log_entry)
    print(f"✓  Log updated: {LOG_FILE}")

    # Move folder
    PROCESSED.mkdir(parents=True, exist_ok=True)
    dest = PROCESSED / folder_date
    shutil.move(str(folder), str(dest))
    print(f"✓  Moved inbox/{folder_date} → inbox/processed/{folder_date}")


def cmd_add_teams(folder_date: str, commit: bool = False) -> None:
    """
    Scan extracted-games.json for teams not yet in the Teams sheet,
    infer their grade and gender from screenshot filenames (and team names
    for mixed-grade brackets), then optionally write them to the Teams sheet.
    """
    folder = INBOX / folder_date
    extracted_file = folder / "extracted-games.json"
    if not extracted_file.exists():
        sys.exit(f"ERROR: {extracted_file} not found. Run extraction first.")

    extracted = json.loads(extracted_file.read_text())

    # Build: team_name → set of source screenshot paths
    team_screenshots: dict[str, set] = {}
    for g in extracted:
        for key in ("home_team", "away_team"):
            name = str(g.get(key, "")).strip()
            src = str(g.get("source_screenshot", "")).strip()
            if name and src:
                team_screenshots.setdefault(name, set()).add(src)

    print("Fetching existing teams from Google Sheets…")
    try:
        existing_rows = get_teams_full()
    except Exception as e:
        sys.exit(f"ERROR fetching teams: {e}")

    def _team_key(name, age_group, gender):
        # Normalize: treat "" and "?" both as unknown so dedup works
        def _norm(v):
            v = str(v).strip()
            return "" if v in ("", "?") else v
        return (str(name).strip(), _norm(age_group), _norm(gender))

    # Build existing (name, age_group, gender) set for dedup
    existing_keys: set[tuple] = set()
    for r in existing_rows:
        n = str(r.get("Team Name", "")).strip()
        if n:
            existing_keys.add(_team_key(n, r.get("Age Group", ""), r.get("Gender", "")))

    existing_names = sorted({str(r.get("Team Name", "")).strip() for r in existing_rows} - {""})
    aliases = load_aliases()

    # Determine grade/gender per team
    proposals: list[dict] = []
    needs_review: list[tuple] = []
    blocked: list[str] = []

    for team, screenshots in sorted(team_screenshots.items()):
        # Already a team (exact, alias, or normalized match) → never add a second
        # row under the same name: the site groups games by name, so same-name
        # rows at different grades would share one record.
        matched, _, _ = match_team(team, existing_names, aliases)
        if matched:
            continue
        # Collect (grade, gender) from each screenshot path
        inferred: set[tuple] = set()
        for path in screenshots:
            grade, gender = parse_grade_gender_from_path(path)
            if grade is None:
                grade = infer_grade_from_name(team)
            inferred.add((grade, gender))

        # Drop fully-ambiguous (None, None) entries when ANY screenshot gave partial info
        has_any_info = any(g is not None or ge is not None for (g, ge) in inferred)
        if has_any_info:
            filtered = {(g, ge) for (g, ge) in inferred if g is not None or ge is not None}
        else:
            filtered = inferred

        if len(filtered) > 1:
            blocked.append(f"{team}  ({', '.join(sorted(f'{g}/{ge}' for g, ge in filtered))})")
            continue

        for (grade, gender) in filtered:
            key = _team_key(team, grade or "", gender or "")
            if key in existing_keys:
                continue  # already in sheet
            proposals.append({
                "Team Name": team,
                "Club Name": "",
                "Age Group": grade or "?",
                "Gender": gender or "?",
                "Team Type": "Club",
                "_sources": sorted(screenshots),
            })
            if grade is None or gender is None:
                needs_review.append(team)

    # Print summary
    print(f"\n{'='*66}")
    print(f"NEW TEAMS — {folder_date}")
    print(f"{'='*66}")
    print(f"  Batch teams total   : {len(team_screenshots)}")
    print(f"  Already in sheet    : {len(team_screenshots) - len({p['Team Name'] for p in proposals})}")
    print(f"  New entries to add  : {len(proposals)}")
    if needs_review:
        print(f"  Needs review (? grade/gender): {len(needs_review)}")
    if blocked:
        print(f"\n⚠  {len(blocked)} name(s) appear in more than one grade/gender and were NOT added.")
        print("   Rename them per grade in extracted-games.json (e.g. 'Unite' → 'Unite 4th'):")
        for b in blocked:
            print(f"     {b}")

    if not proposals:
        print("\nAll teams are already in the Teams sheet.")
        return

    print(f"\n{'─'*66}")
    print(f"{'Team Name':<35} {'Grade':<6} {'Gender':<8} {'Source'}")
    print(f"{'─'*66}")
    for p in proposals:
        src = ", ".join(Path(s).name for s in p["_sources"])[:28]
        flag = " ⚠" if p["Age Group"] == "?" or p["Gender"] == "?" else ""
        print(f"{p['Team Name']:<35} {p['Age Group']:<6} {p['Gender']:<8} {src}{flag}")

    if needs_review:
        print(f"\n⚠  Teams marked ? need manual grade/gender. Edit them in the sheet after adding.")

    if not commit:
        print(f"\nDry run — pass --commit to write these {len(proposals)} entries to the Teams sheet.")
        return

    # Write to Teams sheet
    _sys_path_insert()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import gspread
    import os
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.getenv("TEAMS_SHEET_ID")
    if not creds_json:
        sys.exit("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
    if not sheet_id:
        sys.exit("ERROR: TEAMS_SHEET_ID not set in .env")

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(sheet_id).get_worksheet(0)
    headers = ws.row_values(1)
    if not headers:
        sys.exit("ERROR: Teams sheet has no header row.")

    all_rows = [[p.get(h, "") for h in headers] for p in proposals]
    ws.append_rows(all_rows, value_input_option="USER_ENTERED")

    print(f"\n✓  {len(all_rows)} team(s) added to Teams sheet.")
    print("  Go to the sheet and fill in any ? values, then re-run check.")


def cmd_alias(args: list) -> None:
    aliases = load_aliases()
    if not args or args[0] == "list":
        if not aliases:
            print("No aliases saved yet.")
        for k, v in sorted(aliases.items()):
            print(f"  '{k}'  →  '{v}'")
    elif args[0] == "add" and len(args) >= 3:
        key = normalize(args[1])
        canonical = args[2]
        aliases[key] = canonical
        save_aliases(aliases)
        print(f"✓  Alias saved: '{key}'  →  '{canonical}'")
    else:
        print("Usage:  alias list\n        alias add '<raw name>' '<canonical name>'")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd, rest = args[0], args[1:]
    if cmd == "check" and rest:
        cmd_check(rest[0])
    elif cmd == "import" and rest:
        cmd_import(rest[0])
    elif cmd == "add-teams" and rest:
        commit = "--commit" in rest
        date_arg = next((a for a in rest if not a.startswith("--")), None)
        if not date_arg:
            print("Usage: add-teams YYYY-MM-DD [--commit]")
            sys.exit(1)
        cmd_add_teams(date_arg, commit=commit)
    elif cmd == "alias":
        cmd_alias(rest)
    else:
        print(__doc__)
        sys.exit(1)
