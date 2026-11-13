"""Iowa Basketball Rankings — FastAPI application."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ranking import (
    calculate_rankings,
    get_available_seasons,
    get_filter_options,
    build_team_meta,
    season_cycle,
)
from sheets import get_teams, get_games
import tournaments

app = FastAPI(title="Iowa Basketball Rankings")
templates = Jinja2Templates(directory="templates")
templates.env.filters["date_range"] = tournaments.date_range
templates.env.filters["money"] = tournaments.money
templates.env.filters["short_date"] = tournaments.short_date
templates.env.filters["grade_label"] = tournaments.grade_label


@app.get("/", response_class=HTMLResponse)
@app.get("/rankings", response_class=HTMLResponse)
async def index(
    request: Request,
    season: str = "",
    gender: str = "",
    grade: str = "",
    team_type: str = "Club",
):
    error: str | None = None
    rankings: list[dict] = []
    seasons: list[str] = []
    filter_opts: dict = {"grades": [], "genders": []}

    try:
        teams_raw = get_teams()
        games_raw = get_games()

        seasons = get_available_seasons(games_raw)
        filter_opts = get_filter_options(teams_raw)
        teams_meta = build_team_meta(teams_raw)

        # Old links may say 'Fall 2026'; seasons are Fall–Summer cycles ('2026-27')
        season = season_cycle(season) if season else season
        # Default to most recent season
        if not season and seasons:
            season = seasons[0]

        # Default gender to first available
        if not gender and filter_opts["genders"]:
            gender = filter_opts["genders"][0]

        if season:
            rankings = calculate_rankings(
                games_raw=games_raw,
                teams_meta=teams_meta,
                season=season,
                gender=gender,
                grade=grade,
                team_type=team_type,
            )

    except EnvironmentError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"Unexpected error: {exc}"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "rankings": rankings,
            "seasons": seasons,
            "selected_season": season,
            "grades": filter_opts["grades"],
            "genders": filter_opts["genders"],
            "selected_gender": gender,
            "selected_grade": grade,
            "selected_type": team_type,
            "error": error,
        },
    )


@app.get("/tournaments", response_class=HTMLResponse)
def tournament_search(
    request: Request,
    zip: str = "",
    lat: str = "",
    lng: str = "",
    radius: str = "",
    grade: str = "",
    when: str = "",
    max_fee: str = "",
    open: str = "",
):
    ctx = {"request": request, "error": None, "results": [], "place_error": None,
           "has_origin": False, "radius": 100,
           "f": {"zip": zip, "lat": lat, "lng": lng, "radius": radius, "grade": grade,
                 "when": when, "max_fee": max_fee, "open": open},
           "when_options": tournaments.WHEN_OPTIONS, "fee_options": tournaments.FEE_OPTIONS,
           "radius_options": tournaments.RADIUS_OPTIONS, "grades": tournaments.GRADES}
    try:
        ctx.update(tournaments.search(zip, lat, lng, radius, grade, when, max_fee,
                                      open_only=bool(open)))
    except Exception:
        ctx["error"] = "Tournament listings are temporarily unavailable. Please try again soon."
    return templates.TemplateResponse("tournaments.html", ctx)


@app.get("/tournaments/{tid}", response_class=HTMLResponse)
def tournament_detail(request: Request, tid: str):
    t = tournaments.get(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return templates.TemplateResponse("tournament.html", {"request": request, "t": t})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
