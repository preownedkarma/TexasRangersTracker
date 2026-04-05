"""
app.py — Flask web application for the Texas Rangers Tracker.

Routes:
    GET /                   → current series view
    GET /season             → season overview with leaderboards + charts
    GET /season/batting     → full batting leaderboard
    GET /season/pitching    → full pitching leaderboard
    GET /player/<player_id> → player game log + rolling stats chart
"""

import json
import os
import time
import threading
import requests as _requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, abort, redirect, url_for, flash, request

import db
import sync as sync_module

RANGERS_ID       = 140
SEASON_YEAR      = 2026
ESPN_RANGERS_ID  = 13    # ESPN team ID for the Texas Rangers

# Lat/lon for every current MLB stadium — used for Open-Meteo weather forecasts
STADIUM_COORDS = {
    # AL West
    "Globe Life Field":             (32.7473, -97.0837),   # Arlington, TX
    "Minute Maid Park":             (29.7571, -95.3556),   # Houston, TX
    "T-Mobile Park":                (47.5914, -122.3326),  # Seattle, WA
    "Angel Stadium":                (33.8003, -117.8827),  # Anaheim, CA
    "Oakland Coliseum":             (37.7516, -122.2005),  # Oakland, CA
    "Sutter Health Park":           (38.5802, -121.5000),  # Sacramento, CA (A's temp)
    # AL Central
    "Guaranteed Rate Field":        (41.8300, -87.6339),   # Chicago, IL
    "Progressive Field":            (41.4959, -81.6852),   # Cleveland, OH
    "Comerica Park":                (42.3390, -83.0485),   # Detroit, MI
    "Kauffman Stadium":             (39.0517, -94.4803),   # Kansas City, MO
    "American Family Field":        (43.0283, -87.9711),   # Milwaukee, WI
    "Target Field":                 (44.9817, -93.2781),   # Minneapolis, MN
    # AL East
    "Oriole Park at Camden Yards":  (39.2839, -76.6222),   # Baltimore, MD
    "Fenway Park":                  (42.3467, -71.0972),   # Boston, MA
    "Yankee Stadium":               (40.8296, -73.9262),   # Bronx, NY
    "Rogers Centre":                (43.6414, -79.3894),   # Toronto, ON
    "Tropicana Field":              (27.7682, -82.6534),   # St. Petersburg, FL
    # NL West
    "Dodger Stadium":               (34.0739, -118.2400),  # Los Angeles, CA
    "Oracle Park":                  (37.7786, -122.3893),  # San Francisco, CA
    "Petco Park":                   (32.7073, -117.1570),  # San Diego, CA
    "Chase Field":                  (33.4455, -112.0667),  # Phoenix, AZ
    "Coors Field":                  (39.7559, -104.9942),  # Denver, CO
    # NL Central
    "Wrigley Field":                (41.9484, -87.6553),   # Chicago, IL
    "Great American Ball Park":     (39.0979, -84.5082),   # Cincinnati, OH
    "American Family Field":        (43.0283, -87.9711),   # Milwaukee, WI (shared key)
    "PNC Park":                     (40.4469, -80.0057),   # Pittsburgh, PA
    "Busch Stadium":                (38.6226, -90.1928),   # St. Louis, MO
    "Truist Park":                  (33.8908, -84.4678),   # Cumberland, GA
    # NL East
    "Citi Field":                   (40.7571, -73.8458),   # Flushing, NY
    "Citizens Bank Park":           (39.9061, -75.1665),   # Philadelphia, PA
    "Nationals Park":               (38.8730, -77.0074),   # Washington, DC
    "loanDepot park":               (25.7781, -80.2196),   # Miami, FL
    "Truist Park":                  (33.8908, -84.4678),   # Atlanta, GA
}

# WMO weather code → short description (used with Open-Meteo)
_WMO_CODES = {
    0: "Clear",         1: "Mainly Clear",   2: "Partly Cloudy",  3: "Overcast",
    45: "Fog",          48: "Icy Fog",
    51: "Lt Drizzle",   53: "Drizzle",       55: "Hvy Drizzle",
    61: "Lt Rain",      63: "Rain",          65: "Hvy Rain",
    71: "Lt Snow",      73: "Snow",          75: "Hvy Snow",
    77: "Snow Grains",
    80: "Rain Showers", 81: "Rain Showers",  82: "Hvy Showers",
    85: "Snow Showers", 86: "Hvy Snow Shwr",
    95: "Thunderstorm", 96: "T-Storm/Hail",  99: "Svr T-Storm",
}

# Map opponent name keywords → time-zone label used for record splits.
# When Rangers are away, the opponent IS the home team.
# When Rangers are home, the home park is Globe Life Field → CT.
_OPPONENT_TZ = {
    # Eastern Time
    "Yankees":    "ET", "Red Sox":    "ET", "Orioles":  "ET",
    "Blue Jays":  "ET", "Rays":       "ET", "Mets":     "ET",
    "Phillies":   "ET", "Nationals":  "ET", "Braves":   "ET",
    "Marlins":    "ET", "Pirates":    "ET", "Reds":     "ET",
    "Guardians":  "ET", "Tigers":     "ET", "Cardinals": "ET",
    # Central Time
    "White Sox":  "CT", "Cubs":       "CT", "Brewers":  "CT",
    "Twins":      "CT", "Royals":     "CT", "Astros":   "CT",
    "Rangers":    "CT",   # home games
    # Mountain Time
    "Rockies":    "MT", "Diamondbacks": "MT",
    # Pacific Time
    "Dodgers":    "PT", "Giants":     "PT", "Athletics": "PT",
    "Angels":     "PT", "Padres":     "PT", "Mariners":  "PT",
}

def _tz_for_game(game):
    """Return the time-zone label of the HOME ballpark for a given game."""
    if game["rangers_side"] == "home":
        return "CT"   # Globe Life Field, Arlington TX
    opp = game.get("opponent", "")
    for keyword, tz in _OPPONENT_TZ.items():
        if keyword in opp:
            return tz
    return "Other"


# AL West opponents (division rivals)
_AL_WEST_KEYWORDS = {"Astros", "Athletics", "Angels", "Mariners"}

def _is_division_game(game):
    opp = game.get("opponent", "")
    return any(kw in opp for kw in _AL_WEST_KEYWORDS)


def _wl(games):
    """Return (wins, losses) tuple for a list of game dicts."""
    w = sum(1 for g in games if g["result"] == "W")
    l = sum(1 for g in games if g["result"] == "L")
    return w, l

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rangers-tracker-2026")

# ─── Utility helpers ──────────────────────────────────────────────────────────

def ip_to_outs(ip_str):
    """'6.2' → 20 outs."""
    try:
        whole, frac = str(ip_str).split(".")
        return int(whole) * 3 + int(frac)
    except (ValueError, AttributeError):
        return 0


def outs_to_ip(outs):
    """20 outs → '6.2'."""
    return f"{outs // 3}.{outs % 3}"


def safe_avg(h, ab):
    return round(h / ab, 3) if ab > 0 else 0.0


def fmt_avg(val):
    """Format 0.312 → '.312'  (leading zero removed, 3 decimal places)."""
    return f"{val:.3f}".lstrip("0") or ".000"


def era_str(er, outs):
    """Compute ERA from accumulated outs."""
    ip_dec = outs / 3
    if ip_dec == 0:
        return "-.--"
    return f"{er * 9 / ip_dec:.2f}"


def whip_str(h, bb, outs):
    ip_dec = outs / 3
    if ip_dec == 0:
        return "-.--"
    return f"{(h + bb) / ip_dec:.2f}"


def kbb_str(so, bb):
    if bb == 0:
        return f"{so:.1f}" if so else "-.--"
    return f"{so / bb:.2f}"


def qs_flag(ip_str, er):
    """Return 'YES' if pitcher had a Quality Start."""
    try:
        return "YES" if float(ip_str) >= 6.0 and er <= 3 else "NO"
    except (ValueError, TypeError):
        return "NO"


def parse_runs_scored(score_str):
    """'5-3' → 5  (Rangers runs first)."""
    try:
        return int(score_str.split("-")[0])
    except Exception:
        return 0


def parse_runs_allowed(score_str):
    """'5-3' → 3."""
    try:
        return int(score_str.split("-")[1])
    except Exception:
        return 0


# ─── Data helpers ─────────────────────────────────────────────────────────────

def get_game_archive():
    """
    Return all games newest-first, each enriched with per-game team
    batting and pitching totals for the archive list view.
    """
    conn = db.get_conn()

    # Team batting totals per game (exclude two-way players counted as pitchers)
    bat_rows = conn.execute(
        """
        SELECT
            g.game_pk,
            SUM(bl.ab)  AS t_ab,
            SUM(bl.h)   AS t_h,
            SUM(bl.hr)  AS t_hr,
            SUM(bl.rbi) AS t_rbi,
            SUM(bl.bb)  AS t_bb,
            SUM(bl.so)  AS t_so
        FROM games g
        LEFT JOIN batter_lines bl
            ON bl.game_pk = g.game_pk
            AND bl.player_id NOT IN (SELECT DISTINCT player_id FROM pitcher_lines)
        GROUP BY g.game_pk
        """
    ).fetchall()
    bat_map = {r["game_pk"]: dict(r) for r in bat_rows}

    # Team pitching totals per game
    pit_rows = conn.execute(
        """
        SELECT
            game_pk,
            GROUP_CONCAT(ip_str) AS ip_list,
            SUM(er)  AS t_er,
            SUM(h)   AS t_ph,
            SUM(bb)  AS t_pbb,
            SUM(so)  AS t_pso
        FROM pitcher_lines
        GROUP BY game_pk
        """
    ).fetchall()
    pit_map = {r["game_pk"]: dict(r) for r in pit_rows}

    games = conn.execute(
        "SELECT * FROM games ORDER BY date DESC"
    ).fetchall()
    conn.close()

    result = []
    for idx, g in enumerate(games):
        gd  = dict(g)
        pk  = gd["game_pk"]
        bat = bat_map.get(pk, {})
        pit = pit_map.get(pk, {})

        t_ab  = bat.get("t_ab")  or 0
        t_h   = bat.get("t_h")   or 0
        t_hr  = bat.get("t_hr")  or 0
        t_rbi = bat.get("t_rbi") or 0
        t_bb  = bat.get("t_bb")  or 0
        t_so  = bat.get("t_so")  or 0

        outs  = sum(ip_to_outs(x) for x in (pit.get("ip_list") or "").split(",") if x)
        t_er  = pit.get("t_er")  or 0
        t_ph  = pit.get("t_ph")  or 0
        t_pbb = pit.get("t_pbb") or 0
        t_pso = pit.get("t_pso") or 0

        result.append({
            **gd,
            "gp":     len(games) - idx,   # game number (oldest = 1)
            "t_ab":   t_ab,
            "t_h":    t_h,
            "t_hr":   t_hr,
            "t_rbi":  t_rbi,
            "t_bb":   t_bb,
            "t_so":   t_so,
            "t_avg":  fmt_avg(safe_avg(t_h, t_ab)),
            "t_ip":   outs_to_ip(outs),
            "t_er":   t_er,
            "t_era":  era_str(t_er, outs),
            "t_whip": whip_str(t_ph, t_pbb, outs),
            "t_pso":  t_pso,
        })

    return result


def fetch_linescore(game_pk: int, rangers_side: str, opponent: str) -> dict | None:
    """
    Fetch inning-by-inning linescore from MLB Stats API.
    Returns dict with keys: innings, tex_runs/hits/errors, opp_runs/hits/errors,
    tex_label, opp_label.  Returns None on failure.
    """
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/linescore"
    try:
        r = _requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        opp_side = "away" if rangers_side == "home" else "home"
        teams    = data.get("teams", {})
        tex_team = teams.get(rangers_side, {})
        opp_team = teams.get(opp_side,     {})

        # Build per-inning list: {num, tex, opp}  (None = not yet played / X)
        innings = []
        for inn in data.get("innings", []):
            tex_r = inn.get(rangers_side, {}).get("runs")
            opp_r = inn.get(opp_side,     {}).get("runs")
            innings.append({
                "num":  inn.get("num", len(innings) + 1),
                "tex":  tex_r,   # None means 'x' (walk-off)
                "opp":  opp_r,
            })

        return {
            "innings":    innings,
            "tex_runs":   tex_team.get("runs",   0),
            "tex_hits":   tex_team.get("hits",   0),
            "tex_errors": tex_team.get("errors", 0),
            "opp_runs":   opp_team.get("runs",   0),
            "opp_hits":   opp_team.get("hits",   0),
            "opp_errors": opp_team.get("errors", 0),
            "tex_label":  "TEX",
            "opp_label":  opponent[:3].upper() if opponent else "OPP",
        }
    except Exception:
        return None


def get_game_box_score(game_pk):
    """
    Return full box score for a single game:
      game metadata + per-player batting + per-player pitching.
    Returns None if game_pk is not found.
    """
    conn = db.get_conn()
    game_row = conn.execute(
        "SELECT * FROM games WHERE game_pk = ?", (game_pk,)
    ).fetchone()
    if not game_row:
        conn.close()
        return None

    pit_rows = conn.execute(
        "SELECT * FROM pitcher_lines WHERE game_pk = ? ORDER BY id ASC",
        (game_pk,),
    ).fetchall()
    pitcher_ids = {r["player_id"] for r in pit_rows}

    bat_rows = conn.execute(
        "SELECT * FROM batter_lines WHERE game_pk = ? ORDER BY ab DESC, h DESC",
        (game_pk,),
    ).fetchall()
    conn.close()

    # Build per-player batting (exclude two-way pitchers)
    batters = []
    t_ab = t_h = t_hr = t_rbi = t_bb = t_so = 0
    for r in bat_rows:
        if r["player_id"] in pitcher_ids:
            continue
        avg = fmt_avg(safe_avg(r["h"], r["ab"]))
        batters.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "ab":  r["ab"],
            "h":   r["h"],
            "hr":  r["hr"],
            "rbi": r["rbi"],
            "bb":  r["bb"],
            "so":  r["so"],
            "avg": avg,
        })
        t_ab  += r["ab"];  t_h   += r["h"];   t_hr  += r["hr"]
        t_rbi += r["rbi"]; t_bb  += r["bb"];  t_so  += r["so"]

    # Build per-player pitching
    pitchers = []
    t_outs = t_er = t_ph = t_pbb = t_pso = 0
    for r in pit_rows:
        outs  = ip_to_outs(r["ip_str"])
        whip  = whip_str(r["h"], r["bb"], outs)
        era   = era_str(r["er"], outs)
        qs    = qs_flag(r["ip_str"], r["er"])
        pitchers.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "ip":   r["ip_str"],
            "h":    r["h"],
            "er":   r["er"],
            "bb":   r["bb"],
            "so":   r["so"],
            "era":  era,
            "whip": whip,
            "qs":   qs,
        })
        t_outs += outs; t_er  += r["er"]
        t_ph   += r["h"]; t_pbb += r["bb"]; t_pso += r["so"]

    return {
        "game":     dict(game_row),
        "batters":  batters,
        "pitchers": pitchers,
        # team totals
        "t_ab":   t_ab,  "t_h":  t_h,  "t_hr":  t_hr,
        "t_rbi":  t_rbi, "t_bb": t_bb, "t_so":  t_so,
        "t_avg":  fmt_avg(safe_avg(t_h, t_ab)),
        "t_ip":   outs_to_ip(t_outs),
        "t_er":   t_er,
        "t_era":  era_str(t_er, t_outs),
        "t_whip": whip_str(t_ph, t_pbb, t_outs),
        "t_pso":  t_pso,
    }


def get_all_games():
    """Return all games ordered by date ascending."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM games ORDER BY date ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_batter_lines_for_game(game_pk):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM batter_lines WHERE game_pk = ? ORDER BY ab DESC",
        (game_pk,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pitcher_lines_for_game(game_pk):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM pitcher_lines WHERE game_pk = ? ORDER BY id ASC",
        (game_pk,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Series data ──────────────────────────────────────────────────────────────

def get_series_data():
    """
    Return a dict describing the current (most recent) series.
    The 'current series' is defined as the trailing consecutive run of games
    against the same opponent as the most recently played game.
    """
    games = get_all_games()
    if not games:
        return None

    # Walk backwards to find consecutive games vs the same opponent
    last_opponent = games[-1]["opponent"]
    series_games  = []
    for g in reversed(games):
        if g["opponent"] == last_opponent:
            series_games.append(g)
        else:
            break
    series_games.reverse()  # chronological order

    wins   = sum(1 for g in series_games if g["result"] == "W")
    losses = sum(1 for g in series_games if g["result"] == "L")

    # Attach per-game batter/pitcher lines and compute per-game aggregates
    enriched = []
    # Cumulative series totals
    cum_ab = cum_h = cum_hr = cum_rbi = cum_bb = cum_so = 0
    cum_outs = cum_per = cum_pbb = cum_ph = 0

    for g in series_games:
        pitchers = get_pitcher_lines_for_game(g["game_pk"])
        game_pitcher_ids = {p["player_id"] for p in pitchers}
        batters  = [b for b in get_batter_lines_for_game(g["game_pk"])
                    if b["player_id"] not in game_pitcher_ids]

        # Per-game hitting summary
        g_ab  = sum(b["ab"]  for b in batters)
        g_h   = sum(b["h"]   for b in batters)
        g_hr  = sum(b["hr"]  for b in batters)
        g_rbi = sum(b["rbi"] for b in batters)
        g_bb  = sum(b["bb"]  for b in batters)
        g_so  = sum(b["so"]  for b in batters)
        g_avg = safe_avg(g_h, g_ab)
        g_obp = safe_avg(g_h + g_bb, g_ab + g_bb)
        # Per-game pitching summary
        g_outs = sum(ip_to_outs(p["ip_str"]) for p in pitchers)
        g_per  = sum(p["er"]  for p in pitchers)
        g_pbb  = sum(p["bb"]  for p in pitchers)
        g_ph   = sum(p["h"]   for p in pitchers)
        g_pso  = sum(p["so"]  for p in pitchers)
        g_ip   = outs_to_ip(g_outs)
        g_whip = whip_str(g_ph, g_pbb, g_outs)
        g_kbb  = kbb_str(g_pso, g_pbb)
        g_qs   = qs_flag(g_ip, g_per)

        # Enrich each batter with per-game avg for display
        for b in batters:
            b["avg"] = fmt_avg(safe_avg(b["h"], b["ab"]))
        for p in pitchers:
            p_outs_i = ip_to_outs(p["ip_str"])
            p["whip"] = whip_str(p["h"], p["bb"], p_outs_i)
            p["qs"]   = qs_flag(p["ip_str"], p["er"])

        enriched.append({
            **g,
            "batters":  batters,
            "pitchers": pitchers,
            # hitting summary cols
            "g_ab": g_ab, "g_h": g_h, "g_hr": g_hr, "g_rbi": g_rbi,
            "g_bb": g_bb, "g_so": g_so,
            "g_avg": fmt_avg(g_avg), "g_obp": fmt_avg(g_obp),
            # pitching summary cols
            "g_ip": g_ip, "g_er": g_per,
            "g_whip": g_whip, "g_kbb": g_kbb, "g_qs": g_qs,
        })

        # Accumulate series totals
        cum_ab  += g_ab;  cum_h   += g_h;   cum_hr  += g_hr
        cum_rbi += g_rbi; cum_bb  += g_bb;  cum_so  += g_so
        cum_outs += g_outs; cum_per += g_per
        cum_pbb  += g_pbb;  cum_ph  += g_ph

    # Collect all pitcher IDs in this series to exclude from batting totals
    series_pitcher_ids = set()
    for g in series_games:
        for p in get_pitcher_lines_for_game(g["game_pk"]):
            series_pitcher_ids.add(p["player_id"])

    # Build cumulative batter totals (sum across series per player)
    player_bat_totals = {}
    for g in series_games:
        for b in get_batter_lines_for_game(g["game_pk"]):
            pid = b["player_id"]
            if pid in series_pitcher_ids:
                continue
            if pid not in player_bat_totals:
                player_bat_totals[pid] = {
                    "player_id": pid, "player_name": b["player_name"],
                    "ab": 0, "h": 0, "hr": 0, "rbi": 0, "bb": 0, "so": 0,
                }
            for k in ("ab", "h", "hr", "rbi", "bb", "so"):
                player_bat_totals[pid][k] += b[k]

    cum_batters = sorted(player_bat_totals.values(), key=lambda x: x["ab"], reverse=True)
    for b in cum_batters:
        b["avg"] = fmt_avg(safe_avg(b["h"], b["ab"]))
        b["obp"] = fmt_avg(safe_avg(b["h"] + b["bb"], b["ab"] + b["bb"]))

    # Build cumulative pitcher totals
    player_pit_totals = {}
    for g in series_games:
        pitchers_this_game = get_pitcher_lines_for_game(g["game_pk"])
        # The first pitcher in each game is the starter
        starter_pid = pitchers_this_game[0]["player_id"] if pitchers_this_game else None
        for p in pitchers_this_game:
            pid = p["player_id"]
            if pid not in player_pit_totals:
                player_pit_totals[pid] = {
                    "player_id": pid, "player_name": p["player_name"],
                    "outs": 0, "h": 0, "er": 0, "bb": 0, "so": 0,
                    "gs": 0, "qs": 0,
                }
            player_pit_totals[pid]["outs"] += ip_to_outs(p["ip_str"])
            for k in ("h", "er", "bb", "so"):
                player_pit_totals[pid][k] += p[k]
            if pid == starter_pid:
                player_pit_totals[pid]["gs"] += 1
            if qs_flag(p["ip_str"], p["er"]) == "YES":
                player_pit_totals[pid]["qs"] += 1

    cum_pitchers = sorted(player_pit_totals.values(), key=lambda x: x["outs"], reverse=True)
    for p in cum_pitchers:
        p["ip"]   = outs_to_ip(p["outs"])
        p["era"]  = era_str(p["er"], p["outs"])
        p["whip"] = whip_str(p["h"], p["bb"], p["outs"])
        p["kbb"]  = kbb_str(p["so"], p["bb"])

    return {
        "opponent":     last_opponent,
        "wins":         wins,
        "losses":       losses,
        "games":        enriched,
        # Series cumulative totals
        "cum_avg":      fmt_avg(safe_avg(cum_h, cum_ab)),
        "cum_ab":       cum_ab,
        "cum_h":        cum_h,
        "cum_hr":       cum_hr,
        "cum_rbi":      cum_rbi,
        "cum_bb":       cum_bb,
        "cum_so":       cum_so,
        "cum_ip":       outs_to_ip(cum_outs),
        "cum_er":       cum_per,
        "cum_whip":     whip_str(cum_ph, cum_pbb, cum_outs),
        "cum_batters":  cum_batters,
        "cum_pitchers": cum_pitchers,
    }


# ─── Season data ──────────────────────────────────────────────────────────────

def get_season_batting():
    """
    Aggregate batter_lines by player_id across all games.
    Returns list of dicts sorted by AB desc.
    """
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT
            player_id,
            player_name,
            COUNT(DISTINCT game_pk)  AS g,
            SUM(ab)  AS ab,
            SUM(h)   AS h,
            SUM(hr)  AS hr,
            SUM(rbi) AS rbi,
            SUM(bb)  AS bb,
            SUM(so)  AS so,
            SUM(ab + bb) AS pa
        FROM batter_lines
        WHERE player_id NOT IN (SELECT DISTINCT player_id FROM pitcher_lines)
        GROUP BY player_id
        ORDER BY SUM(ab) DESC
        """
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        ab  = r["ab"]
        h   = r["h"]
        bb  = r["bb"]
        so  = r["so"]
        hr  = r["hr"]
        avg = safe_avg(h, ab)
        obp = safe_avg(h + bb, ab + bb)
        pa = r["pa"] if r["pa"] is not None else 0
        iso = round((h - hr) / ab, 3) if ab > 0 else 0.0
        k_pct_val = round(so / (ab + bb), 3) if (ab + bb) > 0 else 0.0
        babip_denom = ab - so - hr
        babip_val = round((h - hr) / babip_denom, 3) if babip_denom > 0 else 0.0

        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":   r["g"],
            "ab":  ab,
            "h":   h,
            "hr":  hr,
            "rbi": r["rbi"],
            "bb":  bb,
            "so":  so,
            "pa":  pa,
            "iso": fmt_avg(iso),
            "iso_val": iso,
            "avg": fmt_avg(avg),
            "obp": fmt_avg(obp),
            "avg_val": avg,
            "obp_val": obp,
            "k_pct":     fmt_avg(k_pct_val),
            "k_pct_val": k_pct_val,
            "babip":     fmt_avg(babip_val),
            "babip_val": babip_val,
        })
    return result


def get_pre_window_batting(n=10):
    """
    Aggregate batter stats for all games BEFORE the last N game dates.
    Returns a dict keyed by player_id — used as the baseline for hot/cold deltas.
    Requires at least 5 AB to be included (avoids noise from 1-AB appearances).
    """
    conn = db.get_conn()
    date_rows = conn.execute(
        "SELECT DISTINCT date FROM games ORDER BY date DESC LIMIT ?", (n,)
    ).fetchall()
    if not date_rows:
        conn.close()
        return {}
    cutoff = date_rows[-1]["date"]  # oldest date IN the rolling window

    rows = conn.execute(
        """
        SELECT
            bl.player_id,
            SUM(bl.ab)  AS ab,
            SUM(bl.h)   AS h,
            SUM(bl.bb)  AS bb,
            SUM(bl.so)  AS so
        FROM batter_lines bl
        JOIN games g ON g.game_pk = bl.game_pk
        WHERE g.date < ?
          AND bl.player_id NOT IN (SELECT DISTINCT player_id FROM pitcher_lines)
        GROUP BY bl.player_id
        HAVING SUM(bl.ab) >= 5
        """,
        (cutoff,),
    ).fetchall()
    conn.close()

    result = {}
    for r in rows:
        ab  = r["ab"]
        h   = r["h"]
        bb  = r["bb"]
        so  = r["so"]
        avg = safe_avg(h, ab)
        obp = safe_avg(h + bb, ab + bb)
        pa  = ab + bb
        k_pct_val = round(so / pa, 3) if pa > 0 else 0.0
        result[r["player_id"]] = {
            "avg_val":   avg,
            "obp_val":   obp,
            "k_pct_val": k_pct_val,
            "ab":        ab,
        }
    return result


def get_rolling_batting(n=10):
    """
    For each batter, compute AVG / OBP / HR / RBI over their last N games.
    Only include players with at least 1 AB in that window.
    Returns list sorted by rolling AVG desc.
    """
    conn = db.get_conn()

    # Get the last N distinct game dates
    date_rows = conn.execute(
        "SELECT DISTINCT date FROM games ORDER BY date DESC LIMIT ?", (n,)
    ).fetchall()
    if not date_rows:
        conn.close()
        return []
    cutoff = date_rows[-1]["date"]

    rows = conn.execute(
        """
        SELECT
            bl.player_id,
            bl.player_name,
            COUNT(DISTINCT bl.game_pk) AS g,
            SUM(bl.ab)  AS ab,
            SUM(bl.h)   AS h,
            SUM(bl.hr)  AS hr,
            SUM(bl.rbi) AS rbi,
            SUM(bl.bb)  AS bb,
            SUM(bl.so)  AS so
        FROM batter_lines bl
        JOIN games g ON g.game_pk = bl.game_pk
        WHERE g.date >= ?
          AND bl.player_id NOT IN (SELECT DISTINCT player_id FROM pitcher_lines)
        GROUP BY bl.player_id
        HAVING SUM(bl.ab) > 0
        ORDER BY SUM(bl.ab) DESC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        ab  = r["ab"]
        h   = r["h"]
        bb  = r["bb"]
        so  = r["so"]
        hr  = r["hr"]
        avg = safe_avg(h, ab)
        obp = safe_avg(h + bb, ab + bb)
        iso = round((h - hr) / ab, 3) if ab > 0 else 0.0
        pa  = ab + bb
        k_pct_val = round(so / pa, 3) if pa > 0 else 0.0
        babip_denom = ab - so - hr
        babip_val = round((h - hr) / babip_denom, 3) if babip_denom > 0 else 0.0
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":   r["g"],
            "ab":  ab,
            "h":   h,
            "hr":  hr,
            "rbi": r["rbi"],
            "bb":  bb,
            "so":  so,
            "iso": fmt_avg(iso),
            "iso_val": iso,
            "avg": fmt_avg(avg),
            "obp": fmt_avg(obp),
            "avg_val": avg,
            "obp_val": obp,
            "k_pct":     fmt_avg(k_pct_val),
            "k_pct_val": k_pct_val,
            "babip":     fmt_avg(babip_val),
            "babip_val": babip_val,
        })

    result.sort(key=lambda x: x["avg_val"], reverse=True)
    return result


def get_rolling_pitching(n=10):
    """
    For each pitcher, aggregate stats over the last N team games.
    Returns list sorted by IP (outs) desc.
    """
    conn = db.get_conn()

    date_rows = conn.execute(
        "SELECT DISTINCT date FROM games ORDER BY date DESC LIMIT ?", (n,)
    ).fetchall()
    if not date_rows:
        conn.close()
        return []
    cutoff = date_rows[-1]["date"]

    rows = conn.execute(
        """
        SELECT
            pl.player_id,
            pl.player_name,
            COUNT(DISTINCT pl.game_pk) AS g,
            SUM(pl.h)   AS h,
            SUM(pl.er)  AS er,
            SUM(pl.bb)  AS bb,
            SUM(pl.so)  AS so,
            GROUP_CONCAT(pl.ip_str, '|') AS ip_list,
            GROUP_CONCAT(pl.er,     '|') AS er_list
        FROM pitcher_lines pl
        JOIN games g ON g.game_pk = pl.game_pk
        WHERE g.date >= ?
        GROUP BY pl.player_id
        """,
        (cutoff,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        ip_parts = (r["ip_list"] or "").split("|")
        er_parts = [(int(x) if x else 0) for x in (r["er_list"] or "").split("|")]
        outs     = sum(ip_to_outs(x) for x in ip_parts)
        qs_count = sum(1 for ip, er in zip(ip_parts, er_parts) if qs_flag(ip, er) == "YES")
        era  = era_str(r["er"], outs)
        whip = whip_str(r["h"], r["bb"], outs)
        kbb  = kbb_str(r["so"], r["bb"])
        fip_est = None
        if outs > 0:
            fip_est = round((3 * r["bb"] - 2 * r["so"]) / (outs / 3) + 3.1, 2)
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":       r["g"],
            "outs":    outs,
            "ip":      outs_to_ip(outs),
            "h":       r["h"],
            "er":      r["er"],
            "bb":      r["bb"],
            "so":      r["so"],
            "qs":      qs_count,
            "gs":      0,
            "era":     era,
            "whip":    whip,
            "kbb":     kbb,
            "fip_est": fip_est,
            "era_val":  float(era)  if era  != "-.--" else 99.0,
            "whip_val": float(whip) if whip != "-.--" else 99.0,
        })

    result.sort(key=lambda x: x["outs"], reverse=True)
    return result


def get_season_pitching():
    """
    Aggregate pitcher_lines by player_id across all games.
    Returns list of dicts sorted by IP (outs) desc.
    """
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT
            player_id,
            player_name,
            COUNT(DISTINCT game_pk) AS g,
            SUM(h)   AS h,
            SUM(er)  AS er,
            SUM(bb)  AS bb,
            SUM(so)  AS so,
            GROUP_CONCAT(ip_str, '|') AS ip_list,
            GROUP_CONCAT(er,     '|') AS er_list
        FROM pitcher_lines
        GROUP BY player_id
        """
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        ip_parts = (r["ip_list"] or "").split("|")
        er_parts = [(int(x) if x else 0) for x in (r["er_list"] or "").split("|")]
        outs     = sum(ip_to_outs(x) for x in ip_parts)
        qs_count = sum(1 for ip, er in zip(ip_parts, er_parts) if qs_flag(ip, er) == "YES")
        era  = era_str(r["er"], outs)
        whip = whip_str(r["h"], r["bb"], outs)
        kbb  = kbb_str(r["so"], r["bb"])
        fip_est = None
        if outs > 0:
            fip_est = round((3 * r["bb"] - 2 * r["so"]) / (outs / 3) + 3.1, 2)
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":       r["g"],
            "outs":    outs,
            "ip":      outs_to_ip(outs),
            "h":       r["h"],
            "er":      r["er"],
            "bb":      r["bb"],
            "so":      r["so"],
            "qs":      qs_count,
            "gs":      0,   # filled in by season_pitching() from API
            "era":     era,
            "whip":    whip,
            "kbb":     kbb,
            "fip_est": fip_est,
            "era_val":  float(era)  if era  != "-.--" else 99.0,
            "whip_val": float(whip) if whip != "-.--" else 99.0,
        })

    result.sort(key=lambda x: x["outs"], reverse=True)
    return result


def fetch_playoff_data():
    """
    Return a dict with:
      - division_rank  : "1st" / "2nd" / etc.
      - division_gb    : "—" (leader) or "-1.5"
      - div_wins/losses: str
      - wc_rank        : wild-card position (1–3 = in, else out)
      - wc_gb          : games back from last WC spot
      - proj_wins      : projected wins over 162 based on current pace
      - playoff_pct    : str like "67.3%" from FanGraphs, or None
    Returns empty dict on total failure.
    """
    out = {}

    # ── MLB Standings (division + wild card) ──────────────────────────────
    try:
        url = (
            f"https://statsapi.mlb.com/api/v1/standings"
            f"?leagueId=103,104&season={SEASON_YEAR}&standingsTypes=regularSeason"
            f"&hydrate=team"
        )
        r = _requests.get(url, timeout=15)
        if r.status_code == 200:
            # Find Rangers in division standings
            for rec in r.json().get("records", []):
                teams = rec.get("teamRecords", [])
                for i, t in enumerate(teams):
                    if t.get("team", {}).get("id") == RANGERS_ID:
                        gb_raw = t.get("gamesBack", "0")
                        gb_str = "—" if str(gb_raw) in ("0", "0.0", "-") else f"-{gb_raw}"
                        w = t.get("wins", 0)
                        l = t.get("losses", 0)
                        out["division_rank"] = _ordinal(i + 1)
                        out["division_gb"]   = gb_str
                        out["div_w"] = w
                        out["div_l"] = l
                        gp = w + l
                        if gp > 0:
                            out["proj_wins"] = round(w / gp * 162)
                        break

            # Wild card: collect all AL teams not in first place, sort by win%
            al_wc = []
            for rec in r.json().get("records", []):
                # leagueId 103 = AL
                if rec.get("league", {}).get("id") != 103:
                    continue
                for t in rec.get("teamRecords", []):
                    tid  = t.get("team", {}).get("id")
                    w    = t.get("wins", 0)
                    l    = t.get("losses", 0)
                    div_rank = next(
                        (i + 1 for i, x in enumerate(rec.get("teamRecords", []))
                         if x.get("team", {}).get("id") == tid),
                        99
                    )
                    al_wc.append({
                        "id": tid,
                        "w": w, "l": l,
                        "pct": w / (w + l) if (w + l) > 0 else 0,
                        "div_rank": t.get("divisionRank", 99),
                    })

            # Sort by pct desc; top-3 non-division-leaders fill WC spots
            non_leaders = [t for t in al_wc if int(t.get("div_rank", 99)) != 1]
            non_leaders.sort(key=lambda x: x["pct"], reverse=True)
            rangers_wc = next((i + 1 for i, t in enumerate(non_leaders) if t["id"] == RANGERS_ID), None)
            if rangers_wc:
                out["wc_rank"] = rangers_wc
                if rangers_wc <= 3:
                    out["wc_gb"] = "—"
                else:
                    # gb from 3rd WC spot
                    cutoff_pct = non_leaders[2]["pct"] if len(non_leaders) >= 3 else 0
                    r_pct      = next((t["pct"] for t in non_leaders if t["id"] == RANGERS_ID), 0)
                    gp_approx  = out.get("div_w", 0) + out.get("div_l", 0)
                    gb_approx  = round((cutoff_pct - r_pct) * gp_approx / 2, 1) if gp_approx else "?"
                    out["wc_gb"] = f"-{gb_approx}"

    except Exception:
        pass

    # ── FanGraphs playoff odds ─────────────────────────────────────────────
    try:
        fg_url = (
            f"https://www.fangraphs.com/api/playoff-odds/odds"
            f"?allTeams=true&season={SEASON_YEAR}&dateDelta=0"
        )
        headers = {"User-Agent": "Mozilla/5.0 (Rangers Tracker)"}
        fg = _requests.get(fg_url, timeout=15, headers=headers)
        if fg.status_code == 200:
            data = fg.json()
            # Response is a list of team objects; find Rangers by teamid or name
            for team in (data if isinstance(data, list) else data.get("teams", [])):
                name = team.get("TeamName", "") or team.get("teamName", "")
                tid  = team.get("TeamId") or team.get("teamId") or team.get("mlbTeamId")
                if "Rangers" in str(name) or str(tid) == str(RANGERS_ID):
                    pct = team.get("makePlayoffs") or team.get("MakePlayoffs") or \
                          team.get("playoffOdds")  or team.get("PlayoffOdds")
                    if pct is not None:
                        try:
                            out["playoff_pct"] = f"{float(pct) * 100:.1f}%"
                        except (ValueError, TypeError):
                            out["playoff_pct"] = str(pct)
                    break
    except Exception:
        pass

    return out


def fetch_forecast_weather(venue, game_dt_utc):
    """
    Fetch an hourly weather forecast from Open-Meteo (free, no API key) for
    the given stadium at the UTC game start time.

    Returns a dict:
        { "condition": str, "temp_f": int, "wind_mph": int, "precip_pct": int }
    or None if the venue is unknown or the request fails.
    """
    coords = STADIUM_COORDS.get(venue)
    if not coords:
        return None
    lat, lon = coords

    # Open-Meteo supports up to 16 days ahead in the standard forecast endpoint.
    target_hour = game_dt_utc.strftime("%Y-%m-%dT%H:00")
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,precipitation_probability,windspeed_10m,weathercode"
        f"&temperature_unit=fahrenheit&windspeed_unit=mph"
        f"&timezone=UTC&forecast_days=16"
    )
    try:
        resp = _requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        hourly = resp.json().get("hourly", {})
        times  = hourly.get("time", [])
        if target_hour not in times:
            return None
        idx = times.index(target_hour)
        wcode     = hourly["weathercode"][idx]
        temp_f    = hourly["temperature_2m"][idx]
        wind_mph  = hourly["windspeed_10m"][idx]
        precip    = hourly["precipitation_probability"][idx]
        return {
            "condition":  _WMO_CODES.get(wcode, f"Code {wcode}"),
            "temp_f":     round(temp_f)   if temp_f   is not None else None,
            "wind_mph":   round(wind_mph) if wind_mph is not None else None,
            "precip_pct": precip          if precip   is not None else None,
        }
    except Exception:
        return None


def fetch_next_series():
    """
    Fetch the next upcoming series for the Rangers from the MLB schedule API.
    Returns a dict:
      {
        opponent      : str,
        venue         : str,
        home_away     : "Home" | "Away",
        games: [
          {
            date      : "2026-04-05",
            game_pk   : int,
            time      : "7:05 PM CDT",
            home_away : str,
            rangers_starter : str | None,
            opp_starter     : str | None,
          }, ...
        ]
      }
    Returns None on failure or if no upcoming games found.
    """
    from datetime import date as _date, timedelta as _td
    today    = _date.today()
    end_date = (today + _td(days=30)).isoformat()
    today    = today.isoformat()
    try:
        url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&teamId={RANGERS_ID}&season={SEASON_YEAR}&gameType=R"
            f"&startDate={today}&endDate={end_date}"
            f"&hydrate=probablePitcher,team,venue"
        )
        r = _requests.get(url, timeout=15)
        if r.status_code != 200:
            return None

        upcoming = []
        for date_entry in r.json().get("dates", []):
            for game in date_entry.get("games", []):
                state = game.get("status", {}).get("abstractGameState", "")
                if state in ("Final", "Live"):
                    continue
                upcoming.append(game)

        if not upcoming:
            return None

        # First upcoming game determines the next opponent
        first = upcoming[0]
        home_id = first.get("teams", {}).get("home", {}).get("team", {}).get("id")
        rangers_side = "home" if home_id == RANGERS_ID else "away"
        opp_side     = "away" if rangers_side == "home" else "home"
        opponent     = first["teams"][opp_side]["team"].get("name", "Unknown")

        # Collect all games of that series (consecutive same opponent)
        series_games = []
        for game in upcoming:
            h_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            r_side = "home" if h_id == RANGERS_ID else "away"
            o_side = "away" if r_side == "home" else "home"
            opp = game["teams"][o_side]["team"].get("name", "")
            if opp != opponent:
                break
            series_games.append((game, r_side, o_side))

        venue = first.get("venue", {}).get("name", "")

        def _probable(game, side):
            pp = game.get("teams", {}).get(side, {}).get("probablePitcher", {})
            return pp.get("fullName") if pp else None

        def _parse_utc(game):
            from datetime import datetime
            dt_str = game.get("gameDate", "")
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return None

        def _fmt_time(utc_dt):
            if not utc_dt:
                return ""
            try:
                from datetime import timedelta
                cdt = utc_dt + timedelta(hours=-5)
                return cdt.strftime("%I:%M %p CDT").lstrip("0")
            except Exception:
                return ""

        games_out = []
        for game, r_side, o_side in series_games:
            game_venue = game.get("venue", {}).get("name", "") or venue
            utc_dt     = _parse_utc(game)
            forecast   = fetch_forecast_weather(game_venue, utc_dt) if utc_dt else None
            games_out.append({
                "date":            game.get("officialDate") or game.get("gameDate", "")[:10],
                "game_pk":         game.get("gamePk"),
                "time":            _fmt_time(utc_dt),
                "home_away":       "Home" if r_side == "home" else "Away",
                "rangers_starter": _probable(game, r_side),
                "opp_starter":     _probable(game, o_side),
                "forecast":        forecast,
            })

        return {
            "opponent":  opponent,
            "venue":     venue,
            "home_away": "Home" if rangers_side == "home" else "Away",
            "games":     games_out,
        }

    except Exception:
        return None


def _ordinal(n):
    """1 → '1st', 2 → '2nd', etc."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


def fetch_team_ranks():
    """
    Call the MLB team stats API for batting and pitching.
    Rank all 30 teams and return the Rangers' position for:
      hitting  — avg, obp, rbi
      pitching — era, whip, earnedRuns
    Returns a dict like:
      {
        "avg":  {"val": ".267", "rank": "8th",  "of": 30},
        "obp":  {...},
        ...
      }
    or an empty dict on failure.
    """
    RANGERS_ID  = 140
    out = {}

    hitting_fields = [
        ("avg",  "avg",          False, lambda v: f"{float(v):.3f}".lstrip("0") or ".000"),
        ("obp",  "obp",          False, lambda v: f"{float(v):.3f}".lstrip("0") or ".000"),
        ("rbi",  "rbi",          False, lambda v: str(int(v))),
        ("hits", "hits",         False, lambda v: str(int(v))),
        ("bb",   "baseOnBalls",  False, lambda v: str(int(v))),
    ]
    pitching_fields = [
        ("era",  "era",          True,  lambda v: f"{float(v):.2f}"),
        ("whip", "whip",         True,  lambda v: f"{float(v):.2f}"),
        ("er",   "earnedRuns",   True,  lambda v: str(int(v))),
        ("k",    "strikeOuts",   False, lambda v: str(int(v))),
        ("pbb",  "baseOnBalls",  True,  lambda v: str(int(v))),
    ]

    for group, fields in (("hitting", hitting_fields), ("pitching", pitching_fields)):
        url = (
            f"https://statsapi.mlb.com/api/v1/teams/stats"
            f"?season={SEASON_YEAR}&sportId=1&stats=season&group={group}&gameType=R"
        )
        try:
            r = _requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            splits = r.json().get("stats", [{}])[0].get("splits", [])
        except Exception:
            continue

        for key, api_key, lower_is_better, fmt in fields:
            rows = []
            for s in splits:
                tid  = s.get("team", {}).get("id")
                raw  = s.get("stat", {}).get(api_key)
                if raw is None:
                    continue
                try:
                    rows.append((tid, float(raw)))
                except (ValueError, TypeError):
                    continue

            if not rows:
                continue

            rows.sort(key=lambda x: x[1], reverse=not lower_is_better)
            total = len(rows)
            rank  = next((i + 1 for i, (tid, _) in enumerate(rows) if tid == RANGERS_ID), None)
            val   = next((v for tid, v in rows if tid == RANGERS_ID), None)
            if rank is None or val is None:
                continue

            out[key] = {
                "val":   fmt(val),
                "rank":  _ordinal(rank),
                "of":    total,
                "rank_n": rank,
            }

    return out


def _norm_name(name: str) -> str:
    """Normalize a player name for fuzzy matching: lowercase, strip punctuation/spaces."""
    import re
    return re.sub(r"[^a-z]", "", name.lower())


def fetch_espn_pitcher_roles() -> dict:
    """
    Fetch pitcher role designations from ESPN's unofficial roster API.
    Returns dict keyed by normalized player name → 'SP' or 'RP'.
    ESPN returns position.abbreviation as 'SP' or 'RP' (not generic 'P').
    Falls back to empty dict on any failure.
    """
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"
        f"/teams/{ESPN_RANGERS_ID}/roster"
    )
    roles = {}
    try:
        r = _requests.get(url, timeout=10)
        if r.status_code != 200:
            return roles
        for group in r.json().get("athletes", []):
            for athlete in group.get("items", []):
                pos  = athlete.get("position", {}).get("abbreviation", "")
                name = athlete.get("fullName", "")
                if pos in ("SP", "RP") and name:
                    roles[_norm_name(name)] = pos
    except Exception:
        pass
    return roles


def fetch_rangers_pitcher_season_stats():
    """
    Fetch per-player pitching stats + roster position for Rangers pitchers.
    roster_role comes from ESPN's roster API (SP/RP) matched by player name,
    falling back to the MLB depth chart if ESPN is unavailable.
    Returns dict keyed by player_id with saves, holds, games_started, roster_role.
    Falls back to empty dict on any failure.
    """
    stats_url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&teamId={RANGERS_ID}&season={SEASON_YEAR}&sportId=1"
    )
    # ── 1. ESPN roster roles (primary source) ─────────────────────────────
    espn_roles = fetch_espn_pitcher_roles()   # norm_name → 'SP'|'RP'

    # ── 2. MLB depth chart roles (fallback if ESPN unavailable) ───────────
    mlb_roles: dict[int, str] = {}
    if not espn_roles:
        roster_url = (
            f"https://statsapi.mlb.com/api/v1/teams/{RANGERS_ID}/roster"
            f"?rosterType=depthChart&season={SEASON_YEAR}"
        )
        try:
            r2 = _requests.get(roster_url, timeout=15)
            if r2.status_code == 200:
                for entry in r2.json().get("roster", []):
                    pid  = entry.get("person", {}).get("id")
                    code = entry.get("position", {}).get("code", "")
                    if pid and code == "S":
                        mlb_roles[pid] = "SP"
        except Exception:
            pass

    # ── 3. Season stats (saves, holds, gamesStarted) ──────────────────────
    result = {}
    try:
        r = _requests.get(stats_url, timeout=15)
        if r.status_code == 200:
            for s in r.json().get("stats", [{}])[0].get("splits", []):
                pid   = s.get("player", {}).get("id")
                pname = s.get("player", {}).get("fullName", "")
                stat  = s.get("stat", {})
                if not pid:
                    continue
                # Resolve role: ESPN by name → MLB depth chart → default RP
                norm  = _norm_name(pname)
                role  = espn_roles.get(norm) or mlb_roles.get(pid, "RP")
                result[pid] = {
                    "saves":         int(stat.get("saves",        0) or 0),
                    "holds":         int(stat.get("holds",        0) or 0),
                    "games_started": int(stat.get("gamesStarted", 0) or 0),
                    "roster_role":   role,
                }
    except Exception:
        pass

    return result


def get_season_overview():
    """Return season record, top batters, top pitchers, and team rank data."""
    games   = get_all_games()
    batting = get_season_batting()
    pitching = get_season_pitching()

    wins   = sum(1 for g in games if g["result"] == "W")
    losses = sum(1 for g in games if g["result"] == "L")

    # ── Split records ──────────────────────────────────────────────────────
    home_w,  home_l  = _wl([g for g in games if g["rangers_side"] == "home"])
    away_w,  away_l  = _wl([g for g in games if g["rangers_side"] == "away"])
    day_w,   day_l   = _wl([g for g in games if (g.get("day_night") or "").lower() == "day"])
    night_w, night_l = _wl([g for g in games if (g.get("day_night") or "").lower() == "night"])
    div_w,   div_l   = _wl([g for g in games if _is_division_game(g)])
    ndiv_w,  ndiv_l  = _wl([g for g in games if not _is_division_game(g)])

    # Record per time zone of the home ballpark
    tz_buckets = {}
    for g in games:
        tz = _tz_for_game(g)
        tz_buckets.setdefault(tz, []).append(g)
    tz_order  = ["ET", "CT", "MT", "PT", "Other"]
    tz_records = [
        {"tz": tz, "w": _wl(tz_buckets[tz])[0], "l": _wl(tz_buckets[tz])[1]}
        for tz in tz_order if tz in tz_buckets
    ]

    ranks    = fetch_team_ranks()
    playoff  = fetch_playoff_data()

    # ── Batter leaderboards (top 3) ───────────────────────────────────────
    MIN_AB = 10
    qual_batters = [b for b in batting if b["ab"] >= MIN_AB]
    top_h   = sorted(batting,      key=lambda x: x["h"],       reverse=True)[:3]
    top_avg = sorted(qual_batters, key=lambda x: x["avg_val"], reverse=True)[:3]
    top_hr  = sorted(batting,      key=lambda x: x["hr"],      reverse=True)[:3]

    # ── Pitcher leaderboards (top 3) ─────────────────────────────────────
    api_stats = fetch_rangers_pitcher_season_stats()
    for p in pitching:
        api = api_stats.get(p["player_id"], {})
        p["saves"]         = api.get("saves",         0)
        p["holds"]         = api.get("holds",         0)
        p["gs"]            = api.get("games_started", 0)
        p["roster_role"]   = api.get("roster_role",   "RP")
        p["role"]          = _pitcher_role(p["roster_role"], p["saves"])

    MIN_SP_OUTS = 9   # at least 3 IP to qualify for ERA/WHIP leaderboard
    starters  = [p for p in pitching if p["role"] == "SP"]
    relievers = [p for p in pitching if p["role"] in ("RP", "CL") and p["g"] > 0]

    top_sp_era  = sorted([p for p in starters if p["outs"] >= MIN_SP_OUTS],
                         key=lambda x: x["era_val"])[:3]
    top_sp_k    = sorted(starters, key=lambda x: x["so"],  reverse=True)[:3]
    top_sp_whip = sorted([p for p in starters if p["outs"] >= MIN_SP_OUTS],
                         key=lambda x: x["whip_val"])[:3]
    top_sp_qs   = sorted(starters, key=lambda x: x["qs"],  reverse=True)[:3]
    top_rp_sv   = sorted(relievers, key=lambda x: x["saves"], reverse=True)[:3]
    top_rp_hld  = sorted(relievers, key=lambda x: x["holds"], reverse=True)[:3]

    return {
        "wins":         wins,
        "losses":       losses,
        "top_batters":  batting[:5],
        "top_pitchers": pitching[:5],
        "ranks":        ranks,
        "playoff":      playoff,
        # split records
        "home_w": home_w, "home_l": home_l,
        "away_w": away_w, "away_l": away_l,
        "day_w":  day_w,  "day_l":  day_l,
        "night_w": night_w, "night_l": night_l,
        "div_w":   div_w,   "div_l":   div_l,
        "ndiv_w":  ndiv_w,  "ndiv_l":  ndiv_l,
        "tz_records": tz_records,
        # leaderboards
        "top_h":        top_h,
        "top_avg":      top_avg,
        "top_hr":       top_hr,
        "top_sp_era":   top_sp_era,
        "top_sp_k":     top_sp_k,
        "top_sp_whip":  top_sp_whip,
        "top_sp_qs":    top_sp_qs,
        "top_rp_sv":    top_rp_sv,
        "top_rp_hld":   top_rp_hld,
    }


# ─── Player data ──────────────────────────────────────────────────────────────

def get_player_data(player_id):
    """
    Return a dict with game log + rolling stats for a player.
    Detects batter vs pitcher by which table has more rows.
    """
    conn = db.get_conn()

    bat_rows = conn.execute(
        """
        SELECT bl.*, g.date, g.opponent, g.result
        FROM batter_lines bl
        JOIN games g ON g.game_pk = bl.game_pk
        WHERE bl.player_id = ?
        ORDER BY g.date ASC
        """,
        (player_id,),
    ).fetchall()

    pit_rows = conn.execute(
        """
        SELECT pl.*, g.date, g.opponent, g.result
        FROM pitcher_lines pl
        JOIN games g ON g.game_pk = pl.game_pk
        WHERE pl.player_id = ?
        ORDER BY g.date ASC
        """,
        (player_id,),
    ).fetchall()

    conn.close()

    bat_rows = [dict(r) for r in bat_rows]
    pit_rows = [dict(r) for r in pit_rows]

    if not bat_rows and not pit_rows:
        return None

    is_pitcher = len(pit_rows) >= len(bat_rows)
    player_name = (pit_rows[0]["player_name"] if is_pitcher else bat_rows[0]["player_name"])

    if not is_pitcher:
        # ── Batter ────────────────────────────────────────────────────────
        tot_ab  = sum(r["ab"]  for r in bat_rows)
        tot_h   = sum(r["h"]   for r in bat_rows)
        tot_hr  = sum(r["hr"]  for r in bat_rows)
        tot_rbi = sum(r["rbi"] for r in bat_rows)
        tot_bb  = sum(r["bb"]  for r in bat_rows)
        tot_so  = sum(r["so"]  for r in bat_rows)

        game_log = []
        for r in bat_rows:
            game_log.append({
                "date":  r["date"],
                "opp":   r["opponent"],
                "result":r["result"],
                "ab":  r["ab"],
                "h":   r["h"],
                "hr":  r["hr"],
                "rbi": r["rbi"],
                "bb":  r["bb"],
                "so":  r["so"],
                "avg": fmt_avg(safe_avg(r["h"], r["ab"])),
            })

        # Rolling 7-game AVG
        rolling_labels = []
        rolling_vals   = []
        for i in range(len(bat_rows)):
            window = bat_rows[max(0, i - 6): i + 1]
            w_ab   = sum(x["ab"] for x in window)
            w_h    = sum(x["h"]  for x in window)
            rolling_labels.append(bat_rows[i]["date"])
            rolling_vals.append(round(safe_avg(w_h, w_ab), 3))

        return {
            "player_id":   player_id,
            "player_name": player_name,
            "is_pitcher":  False,
            "totals": {
                "g":   len(bat_rows),
                "ab":  tot_ab,
                "h":   tot_h,
                "hr":  tot_hr,
                "rbi": tot_rbi,
                "bb":  tot_bb,
                "so":  tot_so,
                "avg": fmt_avg(safe_avg(tot_h, tot_ab)),
                "obp": fmt_avg(safe_avg(tot_h + tot_bb, tot_ab + tot_bb)),
            },
            "game_log":      game_log,
            "chart_labels":  json.dumps(rolling_labels),
            "chart_values":  json.dumps(rolling_vals),
            "chart_label":   "Rolling 7-Game AVG",
            "chart_y_label": "AVG",
        }

    else:
        # ── Pitcher ───────────────────────────────────────────────────────
        tot_outs = sum(ip_to_outs(r["ip_str"]) for r in pit_rows)
        tot_h    = sum(r["h"]  for r in pit_rows)
        tot_er   = sum(r["er"] for r in pit_rows)
        tot_bb   = sum(r["bb"] for r in pit_rows)
        tot_so   = sum(r["so"] for r in pit_rows)

        game_log = []
        for r in pit_rows:
            p_outs = ip_to_outs(r["ip_str"])
            game_log.append({
                "date":  r["date"],
                "opp":   r["opponent"],
                "result":r["result"],
                "ip":  r["ip_str"],
                "h":   r["h"],
                "er":  r["er"],
                "bb":  r["bb"],
                "so":  r["so"],
                "whip": whip_str(r["h"], r["bb"], p_outs),
            })

        # Rolling 7-game WHIP
        rolling_labels = []
        rolling_vals   = []
        for i in range(len(pit_rows)):
            window  = pit_rows[max(0, i - 6): i + 1]
            w_outs  = sum(ip_to_outs(x["ip_str"]) for x in window)
            w_h     = sum(x["h"]  for x in window)
            w_bb    = sum(x["bb"] for x in window)
            w_val   = round((w_h + w_bb) / (w_outs / 3), 2) if w_outs > 0 else 0.0
            rolling_labels.append(pit_rows[i]["date"])
            rolling_vals.append(w_val)

        return {
            "player_id":   player_id,
            "player_name": player_name,
            "is_pitcher":  True,
            "totals": {
                "g":    len(pit_rows),
                "ip":   outs_to_ip(tot_outs),
                "h":    tot_h,
                "er":   tot_er,
                "bb":   tot_bb,
                "so":   tot_so,
                "era":  era_str(tot_er, tot_outs),
                "whip": whip_str(tot_h, tot_bb, tot_outs),
                "kbb":  kbb_str(tot_so, tot_bb),
            },
            "game_log":      game_log,
            "chart_labels":  json.dumps(rolling_labels),
            "chart_values":  json.dumps(rolling_vals),
            "chart_label":   "Rolling 7-Game WHIP",
            "chart_y_label": "WHIP",
        }


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    db.init_db()
    data        = get_series_data()
    next_series = fetch_next_series()
    return render_template("series_detail.html", series=data, next_series=next_series)


@app.route("/season")
def season():
    db.init_db()
    games = get_all_games()
    if not games:
        return render_template("season.html", overview=None)
    overview = get_season_overview()
    return render_template("season.html", overview=overview)


# Cache: {data: dict, ts: float} — refreshed every 15 minutes
_splits_cache: dict = {"data": {}, "ts": 0.0}
_splits_lock = threading.Lock()
_SPLITS_TTL  = 900   # seconds

# Pitching splits cache (ERA vs LHB / RHB) — ts=0 forces fresh fetch on first load
_p_splits_cache: dict = {"data": {}, "ts": 0.0}
_p_splits_lock = threading.Lock()


def _pitcher_role(roster_role: str, saves: int) -> str:
    """Derive SP / CL / RP from MLB depth chart position + saves."""
    if roster_role == "SP":
        return "SP"
    if saves >= 3:
        return "CL"
    return "RP"


def _fetch_splits_for_player(pid):
    """Fetch vl/vr splits for a single player ID. Returns (pid, {vl:[h,ab], vr:[h,ab]})."""
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{pid}/stats"
        f"?stats=statSplits&group=hitting&season={SEASON_YEAR}&sitCodes=vl,vr&sportId=1"
    )
    raw = {"vl": [0, 0], "vr": [0, 0]}
    try:
        r = _requests.get(url, timeout=10)
        if r.status_code != 200:
            return pid, raw
        for stat_obj in r.json().get("stats", []):
            for s in stat_obj.get("splits", []):
                code = s.get("split", {}).get("code", "")
                if code not in ("vl", "vr"):
                    continue
                stat = s.get("stat", {})
                raw[code][0] += int(stat.get("hits",   0) or 0)
                raw[code][1] += int(stat.get("atBats", 0) or 0)
    except Exception:
        pass
    return pid, raw


def fetch_batting_splits():
    """
    Fetch vs-LHP / vs-RHP splits for every batter in the local DB.
    Uses per-player API calls (the team endpoint omits recently-added players).
    Calls run in parallel and results are cached for 15 minutes.

    Returns: { player_id: { vl_avg, vl_ab, vl_h, vr_avg, vr_ab, vr_h } }
    """
    with _splits_lock:
        if time.time() - _splits_cache["ts"] < _SPLITS_TTL and _splits_cache["data"]:
            return _splits_cache["data"]

    # Collect every batter ID currently in the DB
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT DISTINCT player_id FROM batter_lines "
        "WHERE player_id NOT IN (SELECT DISTINCT player_id FROM pitcher_lines)"
    ).fetchall()
    conn.close()
    player_ids = [r["player_id"] for r in rows]

    result = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_splits_for_player, pid): pid for pid in player_ids}
        for future in as_completed(futures):
            pid, raw = future.result()
            d = {}
            for code in ("vl", "vr"):
                h, ab = raw[code]
                d[f"{code}_h"]   = h
                d[f"{code}_ab"]  = ab
                d[f"{code}_avg"] = fmt_avg(safe_avg(h, ab)) if ab > 0 else "—"
            result[pid] = d

    with _splits_lock:
        _splits_cache["data"] = result
        _splits_cache["ts"]   = time.time()

    return result


def _fetch_pitching_splits_for_player(pid):
    """Fetch vl/vr pitching splits for a single pitcher. Returns (pid, {vl:[er,outs], vr:[er,outs]}).
    MLB API returns inningsPitched as a string (e.g. '3.2'), not an outs integer."""
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{pid}/stats"
        f"?stats=statSplits&group=pitching&season={SEASON_YEAR}&sitCodes=vl,vr&sportId=1"
    )
    raw = {"vl": [0, 0], "vr": [0, 0]}
    try:
        r = _requests.get(url, timeout=10)
        if r.status_code != 200:
            return pid, raw
        for stat_obj in r.json().get("stats", []):
            for s in stat_obj.get("splits", []):
                code = s.get("split", {}).get("code", "")
                if code not in ("vl", "vr"):
                    continue
                stat = s.get("stat", {})
                raw[code][0] += int(stat.get("earnedRuns", 0) or 0)
                # API returns inningsPitched as "3.2" string, not an outs integer
                ip_str = stat.get("inningsPitched", "0") or "0"
                raw[code][1] += ip_to_outs(str(ip_str))
    except Exception:
        pass
    return pid, raw


def fetch_pitching_splits(force_refresh: bool = False):
    """
    Fetch ERA vs LHB / vs RHB splits for every pitcher in the local DB.
    Uses per-player API calls with group=pitching. Cached for 15 minutes.

    Returns: { player_id: { vl_era, vl_er, vl_outs, vr_era, vr_er, vr_outs } }
    """
    with _p_splits_lock:
        if not force_refresh and time.time() - _p_splits_cache["ts"] < _SPLITS_TTL and _p_splits_cache["data"]:
            return _p_splits_cache["data"]

    conn = db.get_conn()
    rows = conn.execute("SELECT DISTINCT player_id FROM pitcher_lines").fetchall()
    conn.close()
    player_ids = [r["player_id"] for r in rows]

    result = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_pitching_splits_for_player, pid): pid for pid in player_ids}
        for future in as_completed(futures):
            pid, raw = future.result()
            d = {}
            for code in ("vl", "vr"):
                er, outs = raw[code]
                era_val  = round((er * 27) / outs, 2) if outs > 0 else None
                d[f"{code}_er"]   = er
                d[f"{code}_outs"] = outs
                d[f"{code}_era"]  = f"{era_val:.2f}" if era_val is not None else "—"
                d[f"{code}_era_val"] = era_val if era_val is not None else 99.0
            result[pid] = d

    with _p_splits_lock:
        _p_splits_cache["data"] = result
        _p_splits_cache["ts"]   = time.time()

    return result


@app.route("/season/batting")
def season_batting():
    db.init_db()
    n = request.args.get("n", default=10, type=int)
    if n not in (7, 10, 14, 30):
        n = 10
    batters = get_season_batting()
    rolling = get_rolling_batting(n)
    splits  = fetch_batting_splits()
    for lst in (batters, rolling):
        for b in lst:
            sp = splits.get(b["player_id"], {})
            b["vl_avg"] = sp.get("vl_avg", "—")
            b["vl_ab"]  = sp.get("vl_ab",  0)
            b["vl_h"]   = sp.get("vl_h",   0)
            b["vr_avg"] = sp.get("vr_avg", "—")
            b["vr_ab"]  = sp.get("vr_ab",  0)
            b["vr_h"]   = sp.get("vr_h",   0)
    return render_template("batting.html", batters=batters, rolling=rolling, rolling_window=n)


@app.route("/season/pitching")
def season_pitching():
    db.init_db()
    n = request.args.get("n", default=10, type=int)
    if n not in (7, 10, 14, 30):
        n = 10
    pitchers = get_season_pitching()
    rolling  = get_rolling_pitching(n)
    p_splits  = fetch_pitching_splits()
    api_stats = fetch_rangers_pitcher_season_stats()

    # Merge splits + role into both lists
    for lst in (pitchers, rolling):
        for p in lst:
            sp = p_splits.get(p["player_id"], {})
            p["vl_era"]     = sp.get("vl_era",     "—")
            p["vl_era_val"] = sp.get("vl_era_val", 99.0)
            p["vl_er"]      = sp.get("vl_er",      0)
            p["vl_outs"]    = sp.get("vl_outs",    0)
            p["vr_era"]     = sp.get("vr_era",     "—")
            p["vr_era_val"] = sp.get("vr_era_val", 99.0)
            p["vr_er"]      = sp.get("vr_er",      0)
            p["vr_outs"]    = sp.get("vr_outs",    0)
            api  = api_stats.get(p["player_id"], {})
            sv   = api.get("saves", 0)
            p["saves"]         = sv
            p["holds"]         = api.get("holds",         0)
            p["gs"]            = api.get("games_started", 0)
            p["roster_role"]   = api.get("roster_role",   "RP")
            p["role"]          = _pitcher_role(p["roster_role"], sv)

    return render_template("pitching.html", pitchers=pitchers, rolling=rolling, rolling_window=n)


@app.route("/season/trends")
def season_trends():
    db.init_db()
    n = request.args.get("n", default=10, type=int)
    if n not in (7, 10, 14, 30):
        n = 10

    games = get_all_games()
    runs_data = []
    era_data = []

    for g in games:
        g_runs = parse_runs_scored(g.get("score", "0-0"))
        pitchers = get_pitcher_lines_for_game(g["game_pk"])
        g_outs = sum(ip_to_outs(p["ip_str"]) for p in pitchers)
        g_er = sum(p["er"] for p in pitchers)
        g_era_val = round((g_er * 9) / (g_outs / 3), 2) if g_outs > 0 else None

        runs_data.append({"date": g["date"], "value": g_runs})
        era_data.append({"date": g["date"], "value": g_era_val, "outs": g_outs, "er": g_er})

    for i in range(len(runs_data)):
        window = runs_data[max(0, i - (n - 1)): i + 1]
        run_rel = sum(x["value"] for x in window) / len(window) if window else 0
        runs_data[i]["rolling"] = round(run_rel, 3)

    for i in range(len(era_data)):
        window = era_data[max(0, i - (n - 1)): i + 1]
        w_outs = sum(x["outs"] for x in window)
        w_er = sum(x["er"] for x in window)
        era_val = round((w_er * 9) / (w_outs / 3), 2) if w_outs > 0 else None
        era_data[i]["rolling"] = era_val

    rolling_bat  = get_rolling_batting(n)
    season_bat   = get_season_batting()
    season_map   = {x["player_id"]: x for x in season_bat}
    adv = []
    for p in rolling_bat:
        season_profile = season_map.get(p["player_id"])
        if not season_profile:
            continue
        avg_delta = round(p["avg_val"]   - season_profile["avg_val"],   3)
        obp_delta = round(p["obp_val"]   - season_profile["obp_val"],   3)
        k_delta   = round(p["k_pct_val"] - season_profile["k_pct_val"], 3)
        adv.append({
            "player_id":   p["player_id"],
            "player_name": p["player_name"],
            # Rolling window stats
            "h":           p["h"],
            "rbi":         p["rbi"],
            "rolling_avg": p["avg_val"],
            "rolling_obp": p["obp_val"],
            "k_pct":       p["k_pct"],
            "babip":       p["babip"],
            # Full-season baselines
            "season_avg":  season_profile["avg_val"],
            "season_obp":  season_profile["obp_val"],
            # Deltas: rolling window minus season average
            "delta":       avg_delta,
            "obp_delta":   obp_delta,
            "k_delta":     k_delta,
        })

    adv.sort(key=lambda x: x["delta"], reverse=True)
    top5    = adv[:5]
    bottom5 = adv[-5:][::-1]   # 5 most negative deltas, worst first

    # Per-game box scores for the accordion (newest first)
    game_boxes = []
    for g in reversed(games):
        pitchers = get_pitcher_lines_for_game(g["game_pk"])
        pit_ids  = {p["player_id"] for p in pitchers}
        batters  = [b for b in get_batter_lines_for_game(g["game_pk"])
                    if b["player_id"] not in pit_ids]
        for b in batters:
            b["avg"] = fmt_avg(safe_avg(b["h"], b["ab"]))
        for p in pitchers:
            p_outs   = ip_to_outs(p["ip_str"])
            p["whip"] = whip_str(p["h"], p["bb"], p_outs)
            p["qs"]   = qs_flag(p["ip_str"], p["er"])
        game_boxes.append({**g, "batters": batters, "pitchers": pitchers})

    return render_template(
        "season_trends.html",
        runs_data=runs_data,
        era_data=era_data,
        top5=top5,
        bottom5=bottom5,
        trend_window=n,
        game_boxes=game_boxes,
    )


@app.route("/games")
def game_archive():
    db.init_db()
    games = get_game_archive()
    return render_template("game_archive.html", games=games)


@app.route("/game/<int:game_pk>")
def game_detail(game_pk):
    db.init_db()
    data = get_game_box_score(game_pk)
    if data is None:
        abort(404)
    g = data["game"]
    linescore = fetch_linescore(game_pk, g["rangers_side"], g["opponent"])
    return render_template("game_detail.html", box=data, linescore=linescore)


@app.route("/player/<int:player_id>")
def player(player_id):
    db.init_db()
    data = get_player_data(player_id)
    if data is None:
        abort(404)
    return render_template("player.html", player=data)


@app.route("/debug/next-series")
def debug_next_series():
    """Diagnostic route — shows raw fetch_next_series() output as JSON."""
    from datetime import date as _date, timedelta as _td
    import traceback
    today    = _date.today()
    end_date = (today + _td(days=30)).isoformat()
    today    = today.isoformat()
    try:
        url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&teamId={RANGERS_ID}&season={SEASON_YEAR}&gameType=R"
            f"&startDate={today}&endDate={end_date}"
            f"&hydrate=probablePitcher,team,venue"
        )
        r = _requests.get(url, timeout=15)
        raw = r.json()
        result = fetch_next_series()
        return {"status": r.status_code, "result": result, "raw_dates": len(raw.get("dates", [])),
                "first_games": [
                    {"date": d.get("date"), "games": [
                        {"gamePk": g.get("gamePk"),
                         "state": g.get("status", {}).get("abstractGameState"),
                         "away": g.get("teams", {}).get("away", {}).get("team", {}).get("name"),
                         "home": g.get("teams", {}).get("home", {}).get("team", {}).get("name")}
                        for g in d.get("games", [])
                    ]} for d in raw.get("dates", [])[:5]
                ]}
    except Exception:
        return {"error": traceback.format_exc()}


def backfill_weather():
    """
    Fetch weather from the MLB live feed for any games where weather_condition
    is NULL or empty. Called automatically after each sync.
    """
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT game_pk, roof FROM games "
        "WHERE weather_condition IS NULL OR weather_condition = ''"
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    updated = 0
    for row in rows:
        game_pk = row["game_pk"]
        roof    = row["roof"] or "Open Air"
        weather = sync_module.fetch_weather(game_pk)
        if not weather:
            continue
        w_cond = weather.get("condition", "")
        w_temp = weather.get("temp",      "")
        w_wind = weather.get("wind",      "")
        roof_status = sync_module.infer_roof_status(roof, w_cond, w_wind)
        conn = db.get_conn()
        conn.execute(
            "UPDATE games SET weather_condition=?, weather_temp=?, weather_wind=?, "
            "roof_status=? WHERE game_pk=?",
            (w_cond, w_temp, w_wind, roof_status, game_pk),
        )
        conn.commit()
        conn.close()
        updated += 1

    return updated


def fetch_playoff_picture() -> dict:
    """
    Fetch full MLB standings and build a playoff picture for both leagues.

    Returns:
    {
      "al": {
        "divisions": [
          { "name": "AL West", "teams": [ {team record dict}, ... ] },
          ...
        ],
        "wildcard": [ {team record dict}, ... ],   # top-6 non-div-winners sorted by pct
        "playoff_teams": [ team_id, ... ]          # 6 AL teams currently in
      },
      "nl": { same structure },
      "rangers_id": 140,
      "last_updated": "2026-04-05T01:59:05Z"
    }
    """
    url = (
        f"https://statsapi.mlb.com/api/v1/standings"
        f"?leagueId=103,104&season={SEASON_YEAR}&standingsTypes=regularSeason"
        f"&hydrate=team,division,league"
    )
    try:
        r = _requests.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        records = r.json().get("records", [])
    except Exception:
        return {}

    def _team_row(t: dict, div_winner: bool) -> dict:
        w   = t.get("wins",   0)
        l   = t.get("losses", 0)
        gb  = t.get("gamesBack",         "-")
        wcgb= t.get("wildCardGamesBack", "-")
        pct = w / (w + l) if (w + l) > 0 else 0.0
        streak = t.get("streak", {})
        strk   = streak.get("streakCode", "")
        elim   = t.get("wildCardEliminationNumber", "-")
        return {
            "id":           t.get("team", {}).get("id"),
            "name":         t.get("team", {}).get("name", ""),
            "abbr":         t.get("team", {}).get("abbreviation", ""),
            "div_rank":     int(t.get("divisionRank", 99) or 99),
            "wc_rank":      int(t.get("wildCardRank",  99) or 99) if t.get("wildCardRank") else 99,
            "league_rank":  int(t.get("leagueRank",    99) or 99),
            "w":            w,
            "l":            l,
            "pct":          pct,
            "pct_str":      t.get("leagueRecord", {}).get("pct", ".000"),
            "gb":           "—" if str(gb)   in ("-", "0", "0.0") else gb,
            "wcgb":         "—" if str(wcgb) in ("-", "0", "0.0") else wcgb,
            "streak":       strk,
            "rs":           t.get("runsScored",  0),
            "ra":           t.get("runsAllowed", 0),
            "diff":         t.get("runDifferential", 0),
            "clinched":     t.get("clinched",         False),
            "div_champ":    t.get("divisionChamp",    False),
            "wc_leader":    t.get("wildCardLeader",   False),
            "has_wc":       t.get("hasWildcard",      False),
            "div_winner":   div_winner,
            "elim_wc":      elim,
            "last_updated": t.get("lastUpdated", ""),
        }

    def _build_league(league_id: int) -> dict:
        divisions   = {}
        all_teams   = []
        last_updated = ""

        for rec in records:
            if rec.get("league", {}).get("id") != league_id:
                continue
            div_name = rec.get("division", {}).get("name", "")
            teams    = rec.get("teamRecords", [])
            rows     = []
            for t in teams:
                is_winner = int(t.get("divisionRank", 99) or 99) == 1
                row = _team_row(t, is_winner)
                rows.append(row)
                all_teams.append(row)
                if row["last_updated"]:
                    last_updated = row["last_updated"]
            rows.sort(key=lambda x: x["div_rank"])
            divisions[div_name] = rows

        # Wild card: non-division-winners sorted by pct desc
        non_winners = [t for t in all_teams if not t["div_winner"]]
        non_winners.sort(key=lambda x: (-x["pct"], x["l"]))
        for i, t in enumerate(non_winners):
            t["wc_pos"] = i + 1   # 1-3 = in, 4+ = out

        # Div winners sorted by record for seeding
        div_winners = sorted([t for t in all_teams if t["div_winner"]],
                             key=lambda x: (-x["pct"], x["l"]))
        for i, t in enumerate(div_winners):
            t["seed"] = i + 1

        playoff_ids = {t["id"] for t in div_winners} | {t["id"] for t in non_winners[:3]}

        return {
            "divisions":    [{"name": k, "teams": v} for k, v in divisions.items()],
            "div_winners":  div_winners,
            "wildcard":     non_winners,
            "playoff_ids":  playoff_ids,
            "last_updated": last_updated,
        }

    al = _build_league(103)
    nl = _build_league(104)
    lu = al["last_updated"] or nl["last_updated"]

    return {
        "al":           al,
        "nl":           nl,
        "rangers_id":   RANGERS_ID,
        "last_updated": lu,
    }


@app.route("/playoff")
def playoff_picture():
    db.init_db()
    data = fetch_playoff_picture()
    return render_template("playoff.html", pp=data)


@app.route("/sync", methods=["POST"])
def trigger_sync():
    """Run the MLB API sync, then backfill any missing weather. Redirect with status."""
    try:
        sync_module.sync()
        filled = backfill_weather()
        msg = "Sync complete — database is up to date."
        if filled:
            msg += f" Weather backfilled for {filled} game(s)."
        flash(msg, "success")
    except Exception as exc:
        flash(f"Sync failed: {exc}", "danger")
    return redirect(request.referrer or url_for("index"))


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
