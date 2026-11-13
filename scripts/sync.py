"""Copy published tournaments from the private Tournaments tab to the site database.

usage: uv run python scripts/sync.py [--dry-run]

- Only rows with status 'published' or 'cancelled' go to the site. Drafts stay private.
- The private 'notes' column is never copied.
- Rows with problems are skipped and listed; the rest still sync.
- The site's tournament list is replaced in one transaction, so removing a row from
  the tab (or setting it back to draft) takes it off the site.
"""
import json, os, re, sys
from datetime import date, datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import connect, init_schema  # noqa: E402  (also loads .env)
from tournaments_tab import COLUMNS, TAB  # noqa: E402

PUBLIC = ("published", "cancelled")
GENDERS = {"boys": "Boys", "girls": "Girls", "both": "Both"}
GRADE_MIN, GRADE_MAX = 3, 8


def read_tab() -> list[dict]:
    gc = gspread.authorize(Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]))
    ws = gc.open_by_key(os.environ["TEAMS_SHEET_ID"]).worksheet(TAB)
    vals = ws.get_all_values()
    assert vals and vals[0] == COLUMNS, "Tournaments tab headers changed; update COLUMNS"
    return [dict(zip(COLUMNS, r + [""] * (len(COLUMNS) - len(r)))) for r in vals[1:]]


def parse_date(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unreadable date '{s}'")


def parse_money(s: str) -> float | None:
    s = s.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    if s.lower() == "free":
        return 0.0
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"fee '{s}' isn't a number (put details in the *_fee_notes column)")


def parse_grades(s: str) -> list[int]:
    """'3rd-8th' / '4th,5th,6th' / '3-5, 7th' → sorted grade numbers."""
    out = set()
    for part in re.split(r"[,/;]|\band\b", s):
        nums = [int(n) for n in re.findall(r"\d+", part)]
        if len(nums) == 1:
            out.add(nums[0])
        elif len(nums) == 2 and nums[0] <= nums[1]:
            out.update(range(nums[0], nums[1] + 1))
        elif part.strip():
            raise ValueError(f"unreadable grades '{s}'")
    return sorted(out)


def clean(row: dict, places: dict, zips: dict) -> tuple[dict, list[str]]:
    """Validate one sheet row. Returns (record, warnings); raises ValueError if unusable."""
    warn = []
    g = lambda k: row.get(k, "").strip()
    if not g("name"):
        raise ValueError("missing name")
    start, end = parse_date(g("start_date")), parse_date(g("end_date"))
    if not start:
        raise ValueError("missing start_date")
    end = end or start
    if end < start:
        raise ValueError("end_date is before start_date")

    gender = GENDERS.get(g("gender").lower())
    if not gender:
        raise ValueError(f"gender '{g('gender')}' must be Boys, Girls or Both")

    grades = parse_grades(g("grades"))
    in_range = [n for n in grades if GRADE_MIN <= n <= GRADE_MAX]
    if not in_range:
        raise ValueError(f"no grades in {GRADE_MIN}rd-{GRADE_MAX}th ('{g('grades')}')")
    if len(in_range) < len(grades):
        warn.append(f"grades outside {GRADE_MIN}-{GRADE_MAX} ignored")

    reg, src = g("register_url"), g("source_url")
    if not reg.startswith(("http://", "https://")):
        raise ValueError("register_url must be a web link")
    if not (src.startswith(("http://", "https://")) or src.lower().startswith("email from")):
        raise ValueError("source_url must be a web link or 'email from <organizer>'")

    state = (g("state") or "IA").upper()
    city = g("city")
    zp = g("zip")[:5]
    if (state, city) not in places:
        raise ValueError(f"city '{city}, {state}' not found (check spelling)")
    if zp and zp in zips:
        lat, lng = zips[zp]
    else:
        if zp:
            warn.append(f"ZIP {zp} not found; using city center")
        lat, lng = places[(state, city)]

    rec = {
        "id": g("id"), "status": g("status").lower(), "name": g("name"),
        "series": g("series") or None, "organizer": g("organizer") or None,
        "start_date": start, "end_date": end, "venue": g("venue") or None,
        "city": city, "state": state, "zip": zp or None, "lat": lat, "lng": lng,
        "gender": gender, "grades": g("grades"), "grade_list": in_range,
        "brackets": g("brackets") or None,
        "entry_fee": parse_money(g("entry_fee")), "entry_fee_notes": g("entry_fee_notes") or None,
        "gate_fee_adult": parse_money(g("gate_fee_adult")),
        "gate_fee_student": parse_money(g("gate_fee_student")),
        "gate_fee_notes": g("gate_fee_notes") or None,
        "registration_deadline": parse_date(g("registration_deadline")),
        "register_url": reg, "source_url": src,
        "source_type": g("source_type") or None, "tier": g("tier") or None,
        "last_verified": parse_date(g("last_verified")),
    }
    return rec, warn


FIELDS = ["id", "status", "name", "series", "organizer", "start_date", "end_date", "venue",
          "city", "state", "zip", "lat", "lng", "gender", "grades", "grade_list", "brackets",
          "entry_fee", "entry_fee_notes", "gate_fee_adult", "gate_fee_student",
          "gate_fee_notes", "registration_deadline", "register_url", "source_url",
          "source_type", "tier", "last_verified"]
assert "notes" not in FIELDS


def main(dry_run: bool) -> None:
    rows = read_tab()
    with connect() as conn:
        init_schema(conn)
        places = {(r["state"], r["city"]): (r["lat"], r["lng"])
                  for r in conn.execute("SELECT * FROM places")}
        zips = {r["zip"]: (r["lat"], r["lng"]) for r in conn.execute("SELECT * FROM zips")}

        good, problems, drafts, seen = [], [], 0, set()
        for i, row in enumerate(rows, start=2):
            status = row["status"].strip().lower()
            label = f"row {i} ({row['name'].strip() or 'no name'})"
            if status not in PUBLIC:
                if status not in ("draft", ""):
                    problems.append(f"{label}: unknown status '{status}'")
                elif row["name"].strip():
                    drafts += 1
                continue
            if not row["id"].strip():
                problems.append(f"{label}: missing id"); continue
            if row["id"] in seen:
                problems.append(f"{label}: duplicate id {row['id']}"); continue
            seen.add(row["id"])
            try:
                rec, warns = clean(row, places, zips)
            except ValueError as e:
                problems.append(f"{label}: {e} — skipped"); continue
            problems += [f"{label}: {w}" for w in warns]
            good.append(rec)

        print(f"{len(good)} to publish, {drafts} draft(s) kept private.")
        for p in problems:
            print("  ! " + p)

        current = conn.execute("SELECT count(*) AS n FROM tournaments").fetchone()["n"]
        if not good and current and "--allow-empty" not in sys.argv:
            sys.exit(f"Refusing to empty the site ({current} live). Pass --allow-empty if intended.")
        if dry_run:
            print("Dry run: site not changed."); conn.rollback(); return

        with conn.transaction():
            conn.execute("DELETE FROM tournaments")
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO tournaments ({', '.join(FIELDS)}) "
                    f"VALUES ({', '.join('%(' + f + ')s' for f in FIELDS)})", good)
    print(f"✓ Site now lists {len(good)} tournament(s) (was {current}).")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
