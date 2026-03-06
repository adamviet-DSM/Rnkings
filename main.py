"""Iowa Basketball Rankings — FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ranking import (
    calculate_rankings,
    get_available_seasons,
    get_filter_options,
    build_team_meta,
)
from sheets import get_teams, get_games

app = FastAPI(title="Iowa Basketball Rankings")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
