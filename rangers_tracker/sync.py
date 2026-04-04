"""
sync.py — Syncs the MLB Stats API into the local SQLite DB.

Run directly:
    python sync.py

Only games not already in the DB are fetched and inserted.
"""

import sys
import os
import requests
from datetime import datetime, timezone, timedelta

# Allow running from project root as well
sys.path.insert(0, os.path.dirname(__file__))

import db

# ─── Constants ────────────────────────────────────────────────────────────────

TEAM_ID = 140
SEASON  = 2026
CDT_OFFSET = timedelta(hours=-5)   # UTC-5 (CDT during baseball season)

STADIUM_ROOF = {
    "Globe Life Field":      "Retractable Roof",
    "Minute Maid Park":      "Retractable Roof",
    "T-Mobile Park":         "Retractable Roof",
    "American Family Field": "Retractable Roof",
    "Chase Field":           "Retractable Roof",
    "loanDepot park":        "Retractable Roof",
    "Rogers Centre":         "Retractable Roof",
    "Tropicana Field":       "Dome",
}

# Weather conditions that only occur outdoors (roof must be open)
_OUTDOOR_CONDITIONS = {
    "sunny", "partly cloudy", "cloudy", "overcast", "clear",
    "drizzle", "rain", "fog", "hazy", "wind", "snow",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def infer_roof_status(roof_type, condition, wind):
    """
    Infer whether a retractable-roof stadium had its roof open or closed.

    Returns one of:
      "Closed"   — roof was shut (dome or strong signals)
      "Open"     — roof was open (outdoor weather signals)
      "Open Air" — stadium has no roof
      "Unknown"  — retractable roof but insufficient data to determine
    """
    if roof_type == "Open Air":
        return "Open Air"

    if roof_type == "Dome":
        return "Closed"

    # Retractable Roof — use weather signals
    cond_lower = (condition or "").lower().strip()
    wind_lower = (wind      or "").lower().strip()

    # Explicit MLB API signal
    if "roof closed" in cond_lower:
        return "Closed"
    if "roof open" in cond_lower:
        return "Open"

    # Zero wind + "none" direction → strongly indicates enclosed environment
    if "0 mph" in wind_lower and "none" in wind_lower:
        return "Closed"

    # Outdoor weather condition → roof must be open
    if any(kw in cond_lower for kw in _OUTDOOR_CONDITIONS):
        return "Open"

    return "Unknown"


def ip_to_outs(ip_str):
    """Convert '6.2' → 20 outs (6 full innings × 3 + 2)."""
    try:
        whole, frac = str(ip_str).split(".")
        return int(whole) * 3 + int(frac)
    except (ValueError, AttributeError):
        return 0


def outs_to_ip(outs):
    """Convert 20 outs → '6.2'."""
    return f"{outs // 3}.{outs % 3}"


# ─── API fetchers ─────────────────────────────────────────────────────────────

def fetch_schedule():
    """Return the list of game dicts from the MLB schedule endpoint."""
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&teamId={TEAM_ID}&season={SEASON}&gameType=R"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    games = []
    for date_entry in r.json().get("dates", []):
        for game in date_entry.get("games", []):
            games.append(game)
    return games


def fetch_weather(game_pk):
    """Fetch weather data from the live feed. Returns dict or None."""
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/feed/live"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        w = r.json().get("gameData", {}).get("weather", {})
        condition = w.get("condition", "").strip()
        temp      = w.get("temp", "").strip()
        wind      = w.get("wind", "").strip()
        if not any([condition, temp, wind]):
            return None
        return {
            "condition": condition or "N/A",
            "temp":      temp      or "N/A",
            "wind":      wind      or "N/A",
        }
    except Exception:
        return None


def fetch_boxscore(game_pk, rangers_side):
    """
    Fetch the boxscore for game_pk.
    Returns (hitting_dict, pitching_dict) for the Rangers side,
    or (None, None) on error.
    """
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
            timeout=15,
        )
        if r.status_code != 200:
            return None, None

        box       = r.json()
        team_data = box["teams"][rangers_side]

        # ── Team-level hitting ─────────────────────────────────────────────
        batting = team_data.get("teamStats", {}).get("batting", {})
        obp = float(batting.get("obp", 0) or 0)
        slg = float(batting.get("slg", 0) or 0)
        hitting = {
            "AB":  batting.get("atBats", 0),
            "H":   batting.get("hits", 0),
            "HR":  batting.get("homeRuns", 0),
            "RBI": batting.get("rbi", 0),
            "BB":  batting.get("baseOnBalls", 0),
            "SO":  batting.get("strikeOuts", 0),
            "OPS": f"{obp + slg:.3f}",
        }

        # ── Individual batter lines ────────────────────────────────────────
        batter_lines = []
        for player_id in team_data.get("batters", []):
            bid    = f"ID{player_id}"
            b_data = team_data["players"].get(bid, {})
            b_name = b_data.get("person", {}).get("fullName", "Unknown")
            s      = b_data.get("stats", {}).get("batting", {})
            ab     = s.get("atBats", 0)
            h      = s.get("hits", 0)
            bb     = s.get("baseOnBalls", 0)
            batter_lines.append({
                "id":   player_id,
                "name": b_name,
                "AB":   ab,
                "H":    h,
                "HR":   s.get("homeRuns", 0),
                "RBI":  s.get("rbi", 0),
                "BB":   bb,
                "SO":   s.get("strikeOuts", 0),
            })
        hitting["batters"] = batter_lines

        # ── Team-level pitching ────────────────────────────────────────────
        pt     = team_data.get("teamStats", {}).get("pitching", {})
        ip_str = pt.get("inningsPitched", "0.0")
        p_bb   = pt.get("baseOnBalls", 0)
        p_h    = pt.get("hits", 0)
        p_so   = pt.get("strikeOuts", 0)
        p_er   = pt.get("earnedRuns", 0)
        try:
            ip_val = float(ip_str)
            whip = round((p_bb + p_h) / ip_val, 2) if ip_val > 0 else 0.0
            kbb  = round(p_so / p_bb, 2)            if p_bb > 0  else float(p_so)
            qs   = "YES" if ip_val >= 6.0 and p_er <= 3 else "NO"
        except (ValueError, ZeroDivisionError):
            whip, kbb, qs = 0.0, 0.0, "NO"

        # ── Individual pitcher lines ───────────────────────────────────────
        pitcher_lines = []
        for player_id in team_data.get("pitchers", []):
            pid    = f"ID{player_id}"
            p_data = team_data["players"].get(pid, {})
            p_name = p_data.get("person", {}).get("fullName", "Unknown")
            s      = p_data.get("stats", {}).get("pitching", {})
            p_ip   = s.get("inningsPitched", "0.0")
            ph     = s.get("hits", 0)
            pbb    = s.get("baseOnBalls", 0)
            p_outs = ip_to_outs(p_ip)
            p_whip = round((ph + pbb) / (p_outs / 3), 2) if p_outs > 0 else 0.0
            pitcher_lines.append({
                "id":   player_id,
                "name": p_name,
                "IP":   p_ip,
                "H":    ph,
                "ER":   s.get("earnedRuns", 0),
                "BB":   pbb,
                "SO":   s.get("strikeOuts", 0),
                "WHIP": p_whip,
            })

        pitching = {
            "IP":     ip_str,
            "ER":     p_er,
            "WHIP":   whip,
            "K/BB":   kbb,
            "QS":     qs,
            "pitchers": pitcher_lines,
        }

        return hitting, pitching

    except Exception as exc:
        print(f"  [!] Error fetching boxscore for {game_pk}: {exc}")
        return None, None


# ─── Core sync logic ──────────────────────────────────────────────────────────

def determine_rangers_side(game):
    """Return 'home' or 'away' for the Rangers in this game dict."""
    home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
    return "home" if home_id == TEAM_ID else "away"


def get_opponent_name(game, rangers_side):
    """Return the opponent's team name."""
    opp_side = "away" if rangers_side == "home" else "home"
    return game.get("teams", {}).get(opp_side, {}).get("team", {}).get("name", "Unknown")


def build_score(game, rangers_side):
    """Return 'rangers_runs-opp_runs' string, e.g. '5-3'."""
    teams = game.get("teams", {})
    opp_side = "away" if rangers_side == "home" else "home"
    r_runs   = teams.get(rangers_side, {}).get("score", 0) or 0
    o_runs   = teams.get(opp_side,    {}).get("score", 0) or 0
    return f"{r_runs}-{o_runs}"


def build_result(game, rangers_side):
    """Return 'W' or 'L'."""
    teams    = game.get("teams", {})
    r_winner = teams.get(rangers_side, {}).get("isWinner", False)
    return "W" if r_winner else "L"


def parse_game_time(game):
    """
    Parse the game's UTC datetime string and return a CDT-local time string
    like '7:05 PM CDT', or '' if unavailable.
    """
    dt_str = game.get("gameDate", "")
    if not dt_str:
        return ""
    try:
        utc_dt  = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        cdt_dt  = utc_dt + CDT_OFFSET
        return cdt_dt.strftime("%-I:%M %p CDT")
    except Exception:
        try:
            # Windows doesn't support %-I — fall back to %I
            utc_dt  = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            cdt_dt  = utc_dt + CDT_OFFSET
            return cdt_dt.strftime("%I:%M %p CDT").lstrip("0")
        except Exception:
            return ""


def sync():
    """Main entry point — fetch schedule and sync new Final games to DB."""
    db.init_db()
    print(f"Syncing Rangers {SEASON} season…")

    try:
        games = fetch_schedule()
    except Exception as exc:
        print(f"[ERROR] Could not fetch schedule: {exc}")
        sys.exit(1)

    final_games = [g for g in games if g.get("status", {}).get("abstractGameState") == "Final"]
    print(f"Found {len(final_games)} Final game(s) in schedule.")

    new_count = 0
    for game in final_games:
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        if db.game_exists(game_pk):
            print(f"  [skip] game_pk={game_pk} already in DB")
            continue

        # ── Determine sides and metadata ───────────────────────────────────
        rangers_side = determine_rangers_side(game)
        opponent     = get_opponent_name(game, rangers_side)
        score        = build_score(game, rangers_side)
        result       = build_result(game, rangers_side)
        date_str     = game.get("officialDate", game.get("gameDate", "")[:10])
        venue        = game.get("venue", {}).get("name", "")
        roof         = STADIUM_ROOF.get(venue, "Open Air")
        day_night    = game.get("dayNight", "").capitalize()
        game_time    = parse_game_time(game)

        print(f"  [fetch] {date_str} — Rangers vs {opponent} ({score}) game_pk={game_pk}")

        # ── Weather ────────────────────────────────────────────────────────
        weather = fetch_weather(game_pk) or {}
        w_cond  = weather.get("condition", "")
        w_temp  = weather.get("temp", "")
        w_wind  = weather.get("wind", "")

        roof_status = infer_roof_status(roof, w_cond, w_wind)
        print(f"    [roof] {venue} → {roof} → status: {roof_status}  (cond='{w_cond}', wind='{w_wind}')")

        # ── Boxscore ───────────────────────────────────────────────────────
        hitting, pitching = fetch_boxscore(game_pk, rangers_side)
        if hitting is None:
            print(f"    [!] Skipping game_pk={game_pk} — could not fetch boxscore")
            continue

        # ── Insert game ────────────────────────────────────────────────────
        db.insert_game(
            game_pk      = game_pk,
            date         = date_str,
            opponent     = opponent,
            result       = result,
            score        = score,
            rangers_side = rangers_side,
            venue        = venue,
            roof         = roof,
            roof_status  = roof_status,
            day_night    = day_night,
            game_time    = game_time,
            weather_condition = w_cond,
            weather_temp      = w_temp,
            weather_wind      = w_wind,
        )

        # ── Insert batter lines ────────────────────────────────────────────
        for b in hitting.get("batters", []):
            db.insert_batter_line(
                game_pk     = game_pk,
                player_id   = b["id"],
                player_name = b["name"],
                ab          = b["AB"],
                h           = b["H"],
                hr          = b["HR"],
                rbi         = b["RBI"],
                bb          = b["BB"],
                so          = b["SO"],
            )

        # ── Insert pitcher lines ───────────────────────────────────────────
        for p in pitching.get("pitchers", []):
            db.insert_pitcher_line(
                game_pk     = game_pk,
                player_id   = p["id"],
                player_name = p["name"],
                ip_str      = p["IP"],
                h           = p["H"],
                er          = p["ER"],
                bb          = p["BB"],
                so          = p["SO"],
            )

        new_count += 1
        print(f"    [ok] Inserted {len(hitting['batters'])} batters, "
              f"{len(pitching['pitchers'])} pitchers")

    print(f"\nDone. {new_count} new game(s) added.")


if __name__ == "__main__":
    sync()
