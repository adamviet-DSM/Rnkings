"""Tournament search for the public site. Reads the database only (filled by scripts/sync.py)."""
from datetime import date, datetime, timedelta

from db import connect, miles

CACHE_SECONDS = 60
_cache: dict = {"at": None, "rows": [], "zips": {}}

WHEN_OPTIONS = [("", "All upcoming"), ("weekend", "This weekend"),
                ("30", "Next 30 days"), ("90", "Next 90 days")]
FEE_OPTIONS = [("", "Any fee"), ("200", "Up to $200"), ("250", "Up to $250"),
               ("300", "Up to $300"), ("350", "Up to $350")]
RADIUS_OPTIONS = [25, 50, 100, 150]
GRADES = [3, 4, 5, 6, 7, 8]


def _load() -> tuple[list[dict], dict]:
    now = datetime.now()
    if _cache["at"] and (now - _cache["at"]).total_seconds() < CACHE_SECONDS:
        return _cache["rows"], _cache["zips"]
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tournaments WHERE end_date >= current_date - 1 "
            "ORDER BY start_date, name").fetchall()
        zips = {r["zip"]: (r["lat"], r["lng"])
                for r in conn.execute("SELECT zip, lat, lng FROM zips")}
    _cache.update(at=now, rows=rows, zips=zips)
    return rows, zips


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _date_window(when: str, today: date) -> tuple[date, date | None]:
    if when == "weekend":
        friday = today + timedelta(days=(4 - today.weekday()) % 7)
        if today.weekday() >= 5:          # Sat/Sun: this weekend is now
            friday = today - timedelta(days=today.weekday() - 4)
        return friday, friday + timedelta(days=2)
    if when.isdigit():
        return today, today + timedelta(days=int(when))
    return today, None


def search(zip_code: str = "", lat: str = "", lng: str = "", radius: str = "",
           grade: str = "", when: str = "", max_fee: str = "", open_only: bool = False,
           gender: str = "Boys") -> dict:
    """Filter upcoming tournaments. Returns rows (with 'miles' when a location is given)."""
    rows, zips = _load()
    today = date.today()
    start, end = _date_window(when, today)

    origin, place_error = None, None
    if zip_code:
        origin = zips.get(zip_code.strip()[:5])
        if not origin:
            place_error = f"ZIP {zip_code} isn't an Iowa ZIP code we know."
    elif _num(lat) is not None and _num(lng) is not None:
        origin = (_num(lat), _num(lng))
    rad = _num(radius) or 100

    g = int(grade) if grade.isdigit() else None
    fee = _num(max_fee)

    out = []
    for t in rows:
        if t["end_date"] < start or (end and t["start_date"] > end):
            continue
        if gender and t["gender"] not in (gender, "Both"):
            continue
        if g and g not in t["grade_list"]:
            continue
        if fee is not None and t["entry_fee"] is not None and float(t["entry_fee"]) > fee:
            continue
        deadline = t["registration_deadline"]
        reg_open = t["status"] == "published" and t["start_date"] > today and (
            deadline is None or deadline >= today)
        if open_only and not reg_open:
            continue
        d = None
        if origin and t["lat"] is not None:
            d = miles(origin[0], origin[1], t["lat"], t["lng"])
            if d > rad:
                continue
        out.append({**t, "miles": d, "reg_open": reg_open})
    return {"results": out, "place_error": place_error, "has_origin": origin is not None,
            "radius": int(rad)}


def get(tid: str) -> dict | None:
    with connect() as conn:
        t = conn.execute("SELECT * FROM tournaments WHERE id = %s", (tid,)).fetchone()
    if t:
        today = date.today()
        dl = t["registration_deadline"]
        t["reg_open"] = t["status"] == "published" and t["start_date"] > today and (
            dl is None or dl >= today)
    return t


# ── Display helpers (used as Jinja filters) ─────────────────────────────────

def date_range(t: dict) -> str:
    s, e = t["start_date"], t["end_date"]
    if e == s:
        return f"{s:%a}, {s:%b} {s.day}"                       # Sat, Dec 5
    days = f"{s:%a}–{e:%a}, " if (e - s).days <= 3 else ""
    if e.month == s.month:
        return f"{days}{s:%b} {s.day}–{e.day}"                 # Sat–Sun, Dec 5–6
    return f"{days}{s:%b} {s.day} – {e:%b} {e.day}"            # Sat–Sun, Nov 30 – Dec 1


def money(v) -> str:
    if v is None:
        return ""
    v = float(v)
    return "Free" if v == 0 else (f"${v:,.0f}" if v == int(v) else f"${v:,.2f}")


def short_date(d) -> str:
    return f"{d:%b} {d.day}" if d else ""


def grade_label(t: dict) -> str:
    """{3,4,5,6,7,8} → '3rd–8th grade'; {4,6} → '4th & 6th grade'."""
    nums = t["grade_list"]
    ordn = lambda n: f"{n}{'rd' if n == 3 else 'th'}"
    if len(nums) > 1 and nums == list(range(nums[0], nums[-1] + 1)):
        return f"{ordn(nums[0])}–{ordn(nums[-1])} grade"
    if len(nums) == 1:
        return f"{ordn(nums[0])} grade"
    return ", ".join(ordn(n) for n in nums[:-1]) + f" & {ordn(nums[-1])} grade"
