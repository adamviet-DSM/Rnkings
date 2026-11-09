#!/usr/bin/env python3
"""
One-time repair: fix the Games sheet header and remove the 68 incorrectly-written
Fall 2026 rows (which have empty Game Date because the column had no header).

Run ONCE, then re-run: uv run python scripts/import_weekend.py import 2026-10-31
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import gspread
from google.oauth2.service_account import Credentials

creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
sheet_id = os.getenv("GAMES_SHEET_ID")
if not creds_json or not sheet_id:
    sys.exit("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON or GAMES_SHEET_ID not set in .env")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
client = gspread.authorize(creds)
ws = client.open_by_key(sheet_id).get_worksheet(0)

# Step 1: Fix header row — rename first column from "" to "Game Date"
headers = ws.row_values(1)
print(f"Current headers: {headers}")
if headers[0] == "":
    ws.update_cell(1, 1, "Game Date")
    print("✓  Renamed first column header to 'Game Date'")
elif headers[0] == "Game Date":
    print("  Header already correct.")
else:
    sys.exit(f"ERROR: Unexpected first column header: '{headers[0]}' — aborting.")

# Step 2: Find and delete rows where Game Date is empty AND Season is "Fall 2026"
# (these are the incorrectly-written rows from the failed import)
all_rows = ws.get_all_values()
print(f"\nTotal rows (including header): {len(all_rows)}")

# Find rows to delete (1-indexed, counting from row 2 = first data row)
to_delete = []
for i, row in enumerate(all_rows[1:], start=2):  # row index 1-based
    game_date = row[0].strip() if row else ""
    season = row[8].strip() if len(row) > 8 else ""
    if game_date == "" and season == "Fall 2026":
        to_delete.append(i)

print(f"Rows to delete (empty Game Date, Fall 2026): {len(to_delete)}")

if not to_delete:
    print("Nothing to delete.")
    sys.exit(0)

# Delete from bottom up to preserve row indices
for row_idx in reversed(to_delete):
    ws.delete_rows(row_idx)
    print(f"  Deleted row {row_idx}")

print(f"\n✓  Done. {len(to_delete)} rows removed.")
print("  Now run: uv run python scripts/import_weekend.py check 2026-10-31")
print("           uv run python scripts/import_weekend.py import 2026-10-31")
