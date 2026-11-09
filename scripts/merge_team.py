"""Merge a team that was split by bracket into its real team.
usage: uv run python scripts/merge_team.py "<from name>" "<into name>" [--commit]
Renames every Games cell from -> into, then deletes the 'from' row in Teams."""
import json, os, sys
import gspread
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv(usecwd=True))
src, dst = sys.argv[1].strip(), sys.argv[2].strip()
commit = "--commit" in sys.argv
assert src != dst, "from and into must be different teams"
gc = gspread.authorize(Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]))

tws = gc.open_by_key(os.environ["TEAMS_SHEET_ID"]).get_worksheet(0)
tv = tws.get_all_values(); TN = tv[0].index("Team Name")
names = [r[TN].strip() for r in tv[1:]]
assert names.count(dst) == 1, f"'{dst}' must exist exactly once in Teams"
src_rows = [i for i, n in enumerate(names, start=2) if n == src]
assert len(src_rows) == 1, f"'{src}' must exist exactly once in Teams: {src_rows}"

gws = gc.open_by_key(os.environ["GAMES_SHEET_ID"]).get_worksheet(0)
gv = gws.get_all_values(); gh = gv[0]
H, A, HS, AS, EV = (gh.index(c) for c in ("Home Team Name", "Away Team Name", "Home Score", "Away Score", "Event Name"))
cells = []
for i, r in enumerate(gv[1:], start=2):
    for c in (H, A):
        if r[c].strip() == src:
            cells.append((i, c + 1))
            print(f"Games row {i}: {r[EV][:30]}  {r[H]} {r[HS]}-{r[AS]} {r[A]}   '{src}' -> '{dst}'")
print(f"Teams row {src_rows[0]}: delete '{src}'")
if not commit:
    print("Dry run. Pass --commit to write."); sys.exit()

gws.batch_update([{"range": gspread.utils.rowcol_to_a1(i, c), "values": [[dst]]} for i, c in cells])
assert tws.cell(src_rows[0], TN + 1).value.strip() == src
tws.delete_rows(src_rows[0])
gv2 = gws.get_all_values()
assert all(gv2[i - 1][c - 1] == dst for i, c in cells)
assert src not in [r[TN].strip() for r in tws.get_all_values()[1:]]
print(f"✓ {len(cells)} game cells moved and '{src}' removed from Teams.")
