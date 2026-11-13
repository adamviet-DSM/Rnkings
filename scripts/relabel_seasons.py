"""Rewrite the Games sheet's Season column as Fall–Summer cycles ('Fall 2026' → '2026-27').
usage: uv run python scripts/relabel_seasons.py [--commit]   (dry run by default)"""
import collections, json, os, sys
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from ranking import season_cycle

gc = gspread.authorize(Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]))
ws = gc.open_by_key(os.environ["GAMES_SHEET_ID"]).get_worksheet(0)
vals = ws.get_all_values()
col = vals[0].index("Season")

changes = collections.Counter()
new_col = []
for row in vals[1:]:
    old = row[col] if col < len(row) else ""
    new = season_cycle(old)
    if new != old:
        changes[(old, new)] += 1
    new_col.append([new])
for (old, new), n in changes.items():
    print(f"  {n:4} rows  '{old}' -> '{new}'")
unknown = {r[0] for r in new_col if r[0] and "-" not in r[0]}
assert not unknown, f"unrecognized season labels: {unknown}"
if not changes:
    print("Nothing to change."); sys.exit()
if "--commit" not in sys.argv:
    print("Dry run. Pass --commit to write."); sys.exit()

rng = f"{gspread.utils.rowcol_to_a1(2, col + 1)}:{gspread.utils.rowcol_to_a1(len(vals), col + 1)}"
assert ws.get_all_values() == vals, "sheet changed since read; re-run"
ws.update(values=new_col, range_name=rng)
check = [r[col] for r in ws.get_all_values()[1:]]
assert check == [r[0] for r in new_col], "verify failed"
print(f"✓ {sum(changes.values())} rows relabeled and verified.")
