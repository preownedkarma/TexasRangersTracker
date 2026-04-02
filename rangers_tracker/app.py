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
import requests as _requests
from flask import Flask, render_template, abort, redirect, url_for, flash, request

import db
import sync as sync_module

RANGERS_ID  = 140
SEASON_YEAR = 2026

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
        for p in get_pitcher_lines_for_game(g["game_pk"]):
            pid = p["player_id"]
            if pid not in player_pit_totals:
                player_pit_totals[pid] = {
                    "player_id": pid, "player_name": p["player_name"],
                    "outs": 0, "h": 0, "er": 0, "bb": 0, "so": 0,
                }
            player_pit_totals[pid]["outs"] += ip_to_outs(p["ip_str"])
            for k in ("h", "er", "bb", "so"):
                player_pit_totals[pid][k] += p[k]

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
        avg = safe_avg(h, ab)
        obp = safe_avg(h + bb, ab + bb)
        pa = r["pa"] if r["pa"] is not None else 0
        iso = round((h - r["hr"]) / ab, 3) if ab > 0 else 0.0

        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":   r["g"],
            "ab":  ab,
            "h":   h,
            "hr":  r["hr"],
            "rbi": r["rbi"],
            "bb":  bb,
            "so":  r["so"],
            "pa":  pa,
            "iso": fmt_avg(iso),
            "iso_val": iso,
            "avg": fmt_avg(avg),
            "obp": fmt_avg(obp),
            "avg_val": avg,   # raw float for color-coding
            "obp_val": obp,
        })
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
        avg = safe_avg(h, ab)
        obp = safe_avg(h + bb, ab + bb)
        iso = round((h - r["hr"]) / ab, 3) if ab > 0 else 0.0
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":   r["g"],
            "ab":  ab,
            "h":   h,
            "hr":  r["hr"],
            "rbi": r["rbi"],
            "bb":  bb,
            "so":  r["so"],
            "iso": fmt_avg(iso),
            "iso_val": iso,
            "avg": fmt_avg(avg),
            "obp": fmt_avg(obp),
            "avg_val": avg,
            "obp_val": obp,
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
            GROUP_CONCAT(pl.ip_str) AS ip_list
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
        outs = sum(ip_to_outs(x) for x in (r["ip_list"] or "").split(","))
        era  = era_str(r["er"], outs)
        whip = whip_str(r["h"], r["bb"], outs)
        kbb  = kbb_str(r["so"], r["bb"])
        fip_est = None
        if outs > 0:
            fip_est = round((3 * r["bb"] - 2 * r["so"]) / (outs / 3) + 3.1, 2)
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":    r["g"],
            "outs": outs,
            "ip":   outs_to_ip(outs),
            "h":    r["h"],
            "er":   r["er"],
            "bb":   r["bb"],
            "so":   r["so"],
            "era":  era,
            "whip": whip,
            "kbb":  kbb,
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
            GROUP_CONCAT(ip_str) AS ip_list
        FROM pitcher_lines
        GROUP BY player_id
        """
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        outs = sum(ip_to_outs(x) for x in (r["ip_list"] or "").split(","))
        era  = era_str(r["er"], outs)
        whip = whip_str(r["h"], r["bb"], outs)
        kbb  = kbb_str(r["so"], r["bb"])
        fip_est = None
        if outs > 0:
            fip_est = round((3 * r["bb"] - 2 * r["so"]) / (outs / 3) + 3.1, 2)
        result.append({
            "player_id":   r["player_id"],
            "player_name": r["player_name"],
            "g":    r["g"],
            "outs": outs,
            "ip":   outs_to_ip(outs),
            "h":    r["h"],
            "er":   r["er"],
            "bb":   r["bb"],
            "so":   r["so"],
            "era":  era,
            "whip": whip,
            "kbb":  kbb,
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

        def _fmt_time(game):
            dt_str = game.get("gameDate", "")
            if not dt_str:
                return ""
            try:
                from datetime import datetime, timedelta
                utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                cdt = utc + timedelta(hours=-5)
                return cdt.strftime("%I:%M %p CDT").lstrip("0")
            except Exception:
                return ""

        games_out = []
        for game, r_side, o_side in series_games:
            games_out.append({
                "date":             game.get("officialDate") or game.get("gameDate", "")[:10],
                "game_pk":          game.get("gamePk"),
                "time":             _fmt_time(game),
                "home_away":        "Home" if r_side == "home" else "Away",
                "rangers_starter":  _probable(game, r_side),
                "opp_starter":      _probable(game, o_side),
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
        ("avg",  "avg",         False, lambda v: f"{float(v):.3f}".lstrip("0") or ".000"),
        ("obp",  "obp",         False, lambda v: f"{float(v):.3f}".lstrip("0") or ".000"),
        ("rbi",  "rbi",         False, lambda v: str(int(v))),
    ]
    pitching_fields = [
        ("era",  "era",         True,  lambda v: f"{float(v):.2f}"),
        ("whip", "whip",        True,  lambda v: f"{float(v):.2f}"),
        ("er",   "earnedRuns",  True,  lambda v: str(int(v))),
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


@app.route("/season/batting")
def season_batting():
    db.init_db()
    n = request.args.get("n", default=10, type=int)
    if n not in (7, 10, 14, 30):
        n = 10
    batters  = get_season_batting()
    rolling  = get_rolling_batting(n)
    return render_template("batting.html", batters=batters, rolling=rolling, rolling_window=n)


@app.route("/season/pitching")
def season_pitching():
    db.init_db()
    n = request.args.get("n", default=10, type=int)
    if n not in (7, 10, 14, 30):
        n = 10
    pitchers = get_season_pitching()
    rolling  = get_rolling_pitching(n)
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

    hundred = 100
    rolling_bat = get_rolling_batting(n)
    season_bat = get_season_batting()
    season_map = {x["player_id"]: x for x in season_bat}
    adv = []
    for p in rolling_bat:
        season_profile = season_map.get(p["player_id"])
        if not season_profile:
            continue
        delta = round(p["avg_val"] - season_profile.get("avg_val", 0), 3)
        adv.append({
            "player_id": p["player_id"],
            "player_name": p["player_name"],
            "rolling_avg": p["avg_val"],
            "season_avg": season_profile.get("avg_val", 0),
            "delta": delta,
        })

    adv.sort(key=lambda x: x["delta"], reverse=True)
    top5 = adv[:5]
    bottom5 = sorted(adv, key=lambda x: x["delta"])[:5]

    return render_template(
        "season_trends.html",
        runs_data=runs_data,
        era_data=era_data,
        top5=top5,
        bottom5=bottom5,
        trend_window=n,
    )


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


@app.route("/sync", methods=["POST"])
def trigger_sync():
    """Run the MLB API sync and redirect back with a status message."""
    try:
        sync_module.sync()
        flash("Sync complete — database is up to date.", "success")
    except Exception as exc:
        flash(f"Sync failed: {exc}", "danger")
    return redirect(request.referrer or url_for("index"))


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
