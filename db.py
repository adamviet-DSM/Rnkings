"""Postgres: the public site's data store for tournaments and places.

The private Google Sheet stays the source of truth; scripts/sync.py copies
published tournaments here (never the private notes column). The site only reads.
"""
import csv
import math
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    state  text NOT NULL,
    city   text NOT NULL,
    lat    double precision NOT NULL,
    lng    double precision NOT NULL,
    PRIMARY KEY (state, city)
);

CREATE TABLE IF NOT EXISTS zips (
    zip  text PRIMARY KEY,
    lat  double precision NOT NULL,
    lng  double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS tournaments (
    id                    text PRIMARY KEY,
    status                text NOT NULL,          -- published | cancelled
    name                  text NOT NULL,
    series                text,
    organizer             text,
    start_date            date NOT NULL,
    end_date              date NOT NULL,
    venue                 text,
    city                  text NOT NULL,
    state                 text NOT NULL,
    zip                   text,
    lat                   double precision,
    lng                   double precision,
    gender                text NOT NULL,          -- Boys | Girls | Both
    grades                text NOT NULL,          -- as written, e.g. 3rd-8th
    grade_list            int[] NOT NULL,         -- e.g. {3,4,5,6,7,8}
    brackets              text,
    entry_fee             numeric,
    entry_fee_notes       text,
    gate_fee_adult        numeric,
    gate_fee_student      numeric,
    gate_fee_notes        text,
    registration_deadline date,
    register_url          text NOT NULL,
    source_url            text NOT NULL,
    source_type           text,
    tier                  text,
    last_verified         date,
    synced_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tournaments_start ON tournaments (start_date);
"""


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise EnvironmentError("DATABASE_URL is not set.")
    # The public proxy (used from a laptop) must be encrypted; Railway's private
    # network (used by the live site) is already isolated.
    ssl = "require" if "rlwy.net" in url else "prefer"
    return psycopg.connect(url, sslmode=ssl, connect_timeout=10, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)


def load_geo(conn: psycopg.Connection) -> tuple[int, int]:
    """Replace places and zips with the Census files in data/."""
    with open(ROOT / "data" / "ia_places.csv") as f:
        places = [(r["state"], r["city"], float(r["lat"]), float(r["lng"]))
                  for r in csv.DictReader(f)]
    with open(ROOT / "data" / "ia_zips.csv") as f:
        zips = [(r["zip"], float(r["lat"]), float(r["lng"])) for r in csv.DictReader(f)]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM places")
        cur.executemany("INSERT INTO places VALUES (%s, %s, %s, %s)", places)
        cur.execute("DELETE FROM zips")
        cur.executemany("INSERT INTO zips VALUES (%s, %s, %s)", zips)
    return len(places), len(zips)


def miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


if __name__ == "__main__":
    # uv run python db.py   → create tables (safe to re-run) and load places/ZIPs
    with connect() as conn:
        init_schema(conn)
        p, z = load_geo(conn)
    print(f"✓ Tables ready. Loaded {p} Iowa places and {z} ZIP codes.")
