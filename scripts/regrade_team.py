"""Rename a team and change its grade (team that played up in a higher bracket).
usage: uv run python scripts/regrade_team.py "<old name>" "<new name>" <grade> [--commit]
Renames the Teams row (and sets Age Group) plus every Games cell."""
import json, os, sys
import gspread
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv(usecwd=True))
old, new, grade = sys.argv[1], sys.argv[2], sys.argv[3]
commit = "--commit" in sys.argv
gc = gspread.authorize(Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]))

tws = gc.open_by_key(os.environ["TEAMS_SHEET_ID"]).get_worksheet(0)
tv = tws.get_all_values(); TN, TA = tv[0].index("Team Name"), tv[0].index("Age Group")
names = [r[TN].strip() for r in tv[1:]]
assert new not in names, f"'{new}' already exists; merge instead"
rows = [i for i, n in enumerate(names, start=2) if n == old]
assert len(rows) == 1, f"'{old}' must exist exactly once in Teams: {rows}"
edits = [(tws, rows[0], TN + 1, new), (tws, rows[0], TA + 1, grade)]
print(f"Teams row {rows[0]}: '{old}' ({tv[rows[0]-1][TA]}) -> '{new}' ({grade})")

gws = gc.open_by_key(os.environ["GAMES_SHEET_ID"]).get_worksheet(0)
gv = gws.get_all_values(); gh = gv[0]
H, A, HS, AS, EV = (gh.index(c) for c in ("Home Team Name", "Away Team Name", "Home Score", "Away Score", "Event Name"))
for i, r in enumerate(gv[1:], start=2):
    for c in (H, A):
        if r[c].strip() == old:
            edits.append((gws, i, c + 1, new))
            print(f"Games row {i}: {r[EV][:30]}  {r[H]} {r[HS]}-{r[AS]} {r[A]}")
if not commit:
    print("Dry run. Pass --commit to write."); sys.exit()
for ws in (tws, gws):
    ws.batch_update([{"range": gspread.utils.rowcol_to_a1(i, c), "values": [[v]]} for w, i, c, v in edits if w is ws])
for ws in (tws, gws):
    vals = ws.get_all_values()
    assert all(vals[i - 1][c - 1] == v for w, i, c, v in edits if w is ws)
print(f"✓ {len(edits)} cells written and verified.")
