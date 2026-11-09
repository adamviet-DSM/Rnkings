"""
Iterative ranking algorithm for Iowa Basketball.

Scoring:
  - Win:  WIN_BASE × tier_multiplier × bracket_multiplier
  - Loss: -LOSS_BASE × tier_multiplier × bracket_multiplier × (1 - opponent_quality)

opponent_quality is a value from 0.0 (worst/unknown) to 1.0 (top-ranked).
A loss to the #1 team incurs zero penalty; a loss to the last-place team
incurs the full penalty. The quality values are recalculated each iteration
until convergence.

Playing up (opponent is in a higher grade, from the Teams sheet Age Group):
  - Win:  × (1 + PLAY_UP_WIN_BONUS × grades_up)
  - Loss: opponent_quality is at least PLAY_UP_LOSS_CREDIT × grades_up
          (capped at 1.0), so the penalty is at most halved per grade up.
Older opponents aren't in the grade being ranked, so without this they would
count as quality 0.0 and a loss to them would get the full penalty.
"""

WIN_BASE = 100.0
LOSS_BASE = 35.0
PLAY_UP_WIN_BONUS = 0.25
PLAY_UP_LOSS_CREDIT = 0.5
ITERATIONS = 25
MIN_GAMES = 2

TIER_MULT: dict[str, float] = {
    "National": 3.0,
    "Regional": 2.0,
    "Local": 1.0,
}

BRACKET_MULT: dict[str, float] = {
    "Gold": 1.2,
    "Silver": 1.0,
}


def season_sort_key(season: str) -> tuple[int, int]:
    """Return a (year, month) sort key so seasons order chronologically."""
    season = season.strip()
    month_map = {"Spring": 3, "Summer": 6, "Fall": 8, "Winter": 11}
    for name, month in month_map.items():
        if season.startswith(name):
            rest = season[len(name):].strip()
            if "-" in rest:
                # e.g. "24-25" → start year 2024
                year_str = rest.split("-")[0].strip()
                year = 2000 + int(year_str) if len(year_str) == 2 else int(year_str)
            else:
                year = int(rest)
            return (year, month)
    return (0, 0)


def get_available_seasons(games: list[dict]) -> list[str]:
    """Return seasons present in the games data, newest first."""
    seasons = {g.get("Season", "").strip() for g in games if g.get("Season", "").strip()}
    return sorted(seasons, key=season_sort_key, reverse=True)


def build_team_meta(teams_raw: list[dict]) -> dict[str, list[dict]]:
    """
    Build team_name → [metadata rows] dict.
    A club can have teams at multiple grade levels (e.g. a 4th-grade and a 7th-grade
    'Ankeny Eagles' are tracked separately via Age Group).
    """
    meta: dict[str, list[dict]] = {}
    for row in teams_raw:
        name = str(row.get("Team Name", "")).strip()
        if name:
            if name not in meta:
                meta[name] = []
            meta[name].append(row)
    return meta


def grade_number(age_group: str) -> int | None:
    """'6th' → 6; anything unparseable ('?', '') → None."""
    digits = "".join(ch for ch in str(age_group) if ch.isdigit())
    return int(digits) if digits else None


def _game_score(result: str, tier: str, bracket: str, opp_quality: float,
                grades_up: int = 0) -> float:
    tier_m = TIER_MULT.get(tier, 1.0)
    bracket_m = BRACKET_MULT.get(bracket, 1.0)
    up = max(grades_up, 0)
    if result == "W":
        return WIN_BASE * tier_m * bracket_m * (1.0 + PLAY_UP_WIN_BONUS * up)
    # Loss — penalty is reduced when the opponent is highly ranked or older
    quality = max(opp_quality, min(1.0, PLAY_UP_LOSS_CREDIT * up))
    return -(LOSS_BASE * tier_m * bracket_m * (1.0 - quality))


def calculate_rankings(
    games_raw: list[dict],
    teams_meta: dict[str, dict],
    season: str,
    gender: str,
    grade: str,
    team_type: str,
    min_games: int = MIN_GAMES,
    iterations: int = ITERATIONS,
) -> list[dict]:
    """
    Return a ranked list of team dicts for the given filters.

    Filters (all optional / empty-string = no filter):
        season    – e.g. "Fall 2024"
        gender    – "Boys" | "Girls"
        grade     – "3rd" | "4th" | … | "8th"
        team_type – "Club" | "School"
    """

    # ── 1. Determine which teams are in-scope ────────────────────────────────
    def matches_filter(name: str) -> bool:
        rows = teams_meta.get(name, [])
        if not rows:
            return not (gender or grade or team_type)
        for m in rows:
            ok = True
            if gender and str(m.get("Gender", "")).strip() != gender:
                ok = False
            if ok and grade and str(m.get("Age Group", "")).strip() != grade:
                ok = False
            if ok and team_type and str(m.get("Team Type", "")).strip() != team_type:
                ok = False
            if ok:
                return True
        return False

    def resolve_meta(name: str) -> dict:
        """Return the metadata row matching the active filters, or first row."""
        rows = teams_meta.get(name, [])
        for m in rows:
            if gender and str(m.get("Gender", "")).strip() != gender:
                continue
            if grade and str(m.get("Age Group", "")).strip() != grade:
                continue
            if team_type and str(m.get("Team Type", "")).strip() != team_type:
                continue
            return m
        return rows[0] if rows else {}

    # ── 2. Filter games to the selected season ───────────────────────────────
    season_games = [
        g for g in games_raw
        if str(g.get("Season", "")).strip() == season
    ]

    # ── 3. Build per-team game records ───────────────────────────────────────
    team_games: dict[str, list[dict]] = {}

    for g in season_games:
        home = str(g.get("Home Team Name", "")).strip()
        away = str(g.get("Away Team Name", "")).strip()
        if not home or not away:
            continue

        try:
            home_score = int(g.get("Home Score") or 0)
            away_score = int(g.get("Away Score") or 0)
        except (ValueError, TypeError):
            continue

        if home_score == away_score:
            continue  # skip ties

        tier = str(g.get("Event Tier", "Local")).strip()
        bracket = str(g.get("Bracket Level", "Silver")).strip()
        date = str(g.get("Game Date", "")).strip()

        home_result = "W" if home_score > away_score else "L"
        away_result = "W" if away_score > home_score else "L"

        for team, opponent, result in [(home, away, home_result), (away, home, away_result)]:
            if team not in team_games:
                team_games[team] = []
            team_games[team].append({
                "opponent": opponent,
                "result": result,
                "tier": tier,
                "bracket": bracket,
                "date": date,
                "home_score": home_score,
                "away_score": away_score,
                "is_home": team == home,
                "event_name": str(g.get("Event Name", "")).strip(),
            })

    # ── 4. Keep only in-scope teams with enough games ────────────────────────
    eligible: dict[str, list[dict]] = {
        name: games
        for name, games in team_games.items()
        if len(games) >= min_games and matches_filter(name)
    }

    if not eligible:
        return []

    # ── 5. Iterative ranking ─────────────────────────────────────────────────
    # opponent_quality[team] = 0.0 (worst) … 1.0 (best)
    opp_quality: dict[str, float] = {}

    def team_grade(name: str) -> int | None:
        rows = teams_meta.get(name, [])
        return grade_number(rows[0].get("Age Group", "")) if rows else None

    # How many grades above the team each opponent is (0 if unknown or not older)
    for team, games in eligible.items():
        mine = grade_number(resolve_meta(team).get("Age Group", ""))
        for g in games:
            theirs = team_grade(g["opponent"])
            g["grades_up"] = max(theirs - mine, 0) if mine and theirs else 0

    for _ in range(iterations):
        scores: dict[str, float] = {}
        for team, games in eligible.items():
            total = sum(
                _game_score(g["result"], g["tier"], g["bracket"],
                            opp_quality.get(g["opponent"], 0.0), g["grades_up"])
                for g in games
            )
            scores[team] = total

        ranked_names = sorted(scores, key=lambda t: scores[t], reverse=True)
        n = len(ranked_names)
        opp_quality = {
            team: (n - rank) / (n - 1) if n > 1 else 1.0
            for rank, team in enumerate(ranked_names)
        }

    # ── 6. Build result list ─────────────────────────────────────────────────
    result_list: list[dict] = []
    for rank, team in enumerate(ranked_names, start=1):
        games = eligible[team]
        wins = sum(1 for g in games if g["result"] == "W")
        losses = len(games) - wins
        meta = resolve_meta(team)

        nat_w = sum(1 for g in games if g["result"] == "W" and g["tier"] == "National")
        reg_w = sum(1 for g in games if g["result"] == "W" and g["tier"] == "Regional")
        loc_w = sum(1 for g in games if g["result"] == "W" and g["tier"] == "Local")
        nat_l = sum(1 for g in games if g["result"] == "L" and g["tier"] == "National")
        reg_l = sum(1 for g in games if g["result"] == "L" and g["tier"] == "Regional")
        loc_l = sum(1 for g in games if g["result"] == "L" and g["tier"] == "Local")

        result_list.append({
            "rank": rank,
            "team_name": team,
            "club_name": str(meta.get("Club Name", "")).strip(),
            "age_group": str(meta.get("Age Group", "")).strip(),
            "gender": str(meta.get("Gender", "")).strip(),
            "team_type": str(meta.get("Team Type", "")).strip(),
            "wins": wins,
            "losses": losses,
            "games_played": len(games),
            "win_pct": wins / len(games) if games else 0.0,
            "score": round(scores[team], 1),
            "national_w": nat_w,
            "regional_w": reg_w,
            "local_w": loc_w,
            "national_l": nat_l,
            "regional_l": reg_l,
            "local_l": loc_l,
            "game_log": sorted(games, key=lambda g: g["date"], reverse=True),
        })

    return result_list


def get_filter_options(teams_raw: list[dict]) -> dict:
    """Return available filter values derived from the Teams sheet."""
    grade_order = ["3rd", "4th", "5th", "6th", "7th", "8th"]
    grades_in_data = {
        str(t.get("Age Group", "")).strip()
        for t in teams_raw
        if t.get("Age Group") and str(t.get("Age Group", "")).strip() not in ("", "?")
    }
    grades = [g for g in grade_order if g in grades_in_data]

    genders = sorted({
        str(t.get("Gender", "")).strip()
        for t in teams_raw
        if t.get("Gender") and str(t.get("Gender", "")).strip() not in ("", "?")
    })

    return {"grades": grades, "genders": genders}
