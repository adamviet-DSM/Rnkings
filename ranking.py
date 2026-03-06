"""
Iterative ranking algorithm for Iowa Basketball.

Scoring:
  - Win:  WIN_BASE × tier_multiplier × bracket_multiplier
  - Loss: -LOSS_BASE × tier_multiplier × bracket_multiplier × (1 - opponent_quality)

opponent_quality is a value from 0.0 (worst/unknown) to 1.0 (top-ranked).
A loss to the #1 team incurs zero penalty; a loss to the last-place team
incurs the full penalty. The quality values are recalculated each iteration
until convergence.
"""

WIN_BASE = 100.0
LOSS_BASE = 35.0
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


def build_team_meta(teams_raw: list[dict]) -> dict[str, dict]:
    """
    Build a team_name → metadata dict from the Teams sheet.
    If a team appears multiple times (multiple seasons), keep the last row
    so the most recent metadata wins.
    """
    meta: dict[str, dict] = {}
    for row in teams_raw:
        name = str(row.get("Team Name", "")).strip()
        if name:
            meta[name] = row
    return meta


def _game_score(result: str, tier: str, bracket: str, opp_quality: float) -> float:
    tier_m = TIER_MULT.get(tier, 1.0)
    bracket_m = BRACKET_MULT.get(bracket, 1.0)
    if result == "W":
        return WIN_BASE * tier_m * bracket_m
    # Loss — penalty is reduced when the opponent is highly ranked
    return -(LOSS_BASE * tier_m * bracket_m * (1.0 - opp_quality))


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
        meta = teams_meta.get(name, {})
        if gender and str(meta.get("Gender", "")).strip() != gender:
            return False
        if grade and str(meta.get("Age Group", "")).strip() != grade:
            return False
        if team_type and str(meta.get("Team Type", "")).strip() != team_type:
            return False
        return True

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

    for _ in range(iterations):
        scores: dict[str, float] = {}
        for team, games in eligible.items():
            total = sum(
                _game_score(g["result"], g["tier"], g["bracket"],
                            opp_quality.get(g["opponent"], 0.0))
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
        meta = teams_meta.get(team, {})

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
    grades_in_data = {str(t.get("Age Group", "")).strip() for t in teams_raw}
    grades = [g for g in grade_order if g in grades_in_data]

    genders = sorted({str(t.get("Gender", "")).strip() for t in teams_raw if t.get("Gender")})

    return {"grades": grades, "genders": genders}
