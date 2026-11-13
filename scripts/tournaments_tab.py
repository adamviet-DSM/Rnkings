"""Tournaments tab in the private Teams spreadsheet: the admin view for tournament listings.

usage:
  uv run python scripts/tournaments_tab.py create      # add the tab with headers (once)
  uv run python scripts/tournaments_tab.py add <file.json> [--commit]
      append tournaments (a JSON list of objects keyed by COLUMNS) as drafts

Only facts go here (names, dates, places, grades, fees, links). Rows publish to the
site when status is 'published' and the next sync runs.
"""
import json, os, re, sys
from datetime import date
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TAB = "Tournaments"

COLUMNS = [
    "id",                     # url slug, e.g. carlisle-booster-club-2026-11
    "status",                 # draft | published | cancelled
    "name",
    "series",                 # same tournament across years, e.g. "Carlisle Booster Club"
    "organizer",
    "start_date",             # YYYY-MM-DD
    "end_date",               # YYYY-MM-DD
    "venue",
    "city",
    "state",                  # IA
    "zip",
    "gender",                 # Boys | Girls | Both
    "grades",                 # e.g. 3rd-8th  or  4th,5th,6th
    "brackets",               # e.g. Gold, Silver
    "entry_fee",              # per team, number in dollars
    "entry_fee_notes",
    "gate_fee_adult",
    "gate_fee_student",
    "gate_fee_notes",
    "registration_deadline",  # YYYY-MM-DD
    "register_url",           # official registration page
    "source_url",             # page or email the facts came from
    "source_type",            # email | screenshot | website
    "tier",                   # Local | Regional | National
    "notes",                  # private, never shown on the site
    "added_on",               # YYYY-MM-DD
    "last_verified",          # YYYY-MM-DD
]


def _ws(create=False):
    gc = gspread.authorize(Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    sh = gc.open_by_key(os.environ["TEAMS_SHEET_ID"])
    try:
        return sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        if not create:
            sys.exit(f"No '{TAB}' tab yet. Run: uv run python scripts/tournaments_tab.py create")
        ws = sh.add_worksheet(title=TAB, rows=500, cols=len(COLUMNS))
        ws.update(values=[COLUMNS], range_name="A1")
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
        return ws


def slugify(name: str, start: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{s}-{start[:7]}" if start else s


def cmd_create():
    ws = _ws(create=True)
    header = ws.row_values(1)
    assert header == COLUMNS, f"Tab exists with different headers: {header}"
    print(f"✓ '{TAB}' tab ready with {len(COLUMNS)} columns.")


def cmd_add(path: str, commit: bool):
    items = json.loads(Path(path).read_text())
    ws = _ws()
    assert ws.row_values(1) == COLUMNS, "Tournaments tab headers changed; update COLUMNS"
    existing = set(ws.col_values(1)[1:])
    rows = []
    for t in items:
        unknown = set(t) - set(COLUMNS)
        assert not unknown, f"Unknown fields {unknown} in {t.get('name')}"
        t = {**t}
        t.setdefault("status", "draft")
        t.setdefault("state", "IA")
        t.setdefault("added_on", date.today().isoformat())
        t["id"] = t.get("id") or slugify(t["name"], t.get("start_date", ""))
        if t["id"] in existing:
            print(f"  skip (already in tab): {t['id']}")
            continue
        existing.add(t["id"])
        rows.append([str(t.get(c, "")) for c in COLUMNS])
        print(f"  {t['status']:9} {t['id']}  {t.get('start_date','')}  {t.get('city','')}")
    if not rows:
        print("Nothing to add."); return
    if not commit:
        print(f"Dry run: {len(rows)} row(s). Pass --commit to add."); return
    ws.append_rows(rows, value_input_option="RAW")
    print(f"✓ {len(rows)} tournament(s) added as {rows[0][1]}.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "create":
        cmd_create()
    elif len(sys.argv) >= 3 and sys.argv[1] == "add":
        cmd_add(sys.argv[2], "--commit" in sys.argv)
    else:
        print(__doc__)
