# Texas Rangers Tracker

A Flask web application for tracking the 2026 Texas Rangers season. Game data is pulled from the official MLB Stats API and stored locally in SQLite. No API key required.

---

## Features

**Series View**
- Current series summary with game-by-game results
- Per-game accordion with individual batter and pitcher lines
- Cumulative series totals for batting and pitching
- Next series schedule with projected starting pitchers

**Season Overview**
- W-L record with projected wins, division rank, wild card position, and playoff odds (via FanGraphs)
- Split records: Home/Away, Day/Night, By Time Zone, AL West vs Non-Division
- Top 5 batters and pitchers
- Team ranking among all 30 MLB teams for AVG, OBP, RBI, ERA, WHIP, and ER

**Batting Leaderboard**
- Full season stats: G, AB, H, HR, RBI, BB, SO, AVG, OBP
- Last 10 games rolling stats
- Sortable columns, pitchers excluded

**Pitching Leaderboard**
- Full season stats: G, IP, H, ER, BB, SO, ERA, WHIP, K/BB
- Last 10 games rolling stats
- Sortable columns

**Player Pages**
- Season totals bar
- Full game log
- Rolling 7-game AVG chart (batters) or WHIP chart (pitchers) via Chart.js

**Sync Button**
- One-click data sync from the navbar — pulls all new completed games into the local database

---

## Requirements

- Python 3.9+
- Flask
- Requests

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Setup and Usage

**1. Clone the repository**

```bash
git clone https://github.com/preownedkarma/TexasRangersTracker.git
cd TexasRangersTracker/rangers_tracker
```

**2. Load game data**

```bash
python sync.py
```

This fetches all completed 2026 Rangers games from the MLB Stats API and writes them to a local `rangers.db` SQLite database. Only new games are inserted on subsequent runs.

**3. Start the web server**

```bash
python app.py
```

Open your browser to `http://localhost:5000`.

---

## Project Structure

```
rangers_tracker/
    app.py              Flask application and all route handlers
    db.py               SQLite schema and database helpers
    sync.py             MLB API data sync script
    requirements.txt
    static/
        style.css       Custom dark-theme styles
    templates/
        base.html       Base layout with navbar and Bootstrap 5
        series_detail.html
        season.html
        batting.html
        pitching.html
        player.html
```

---

## Data Sources

- **MLB Stats API** (`statsapi.mlb.com`) — schedule, boxscores, standings, probable pitchers, weather. No authentication required.
- **FanGraphs** — playoff odds percentage. Fetched live on the season overview page. Gracefully omitted if unavailable.

---

## Color Coding

Stat colors are consistent across all views:

| Color  | Meaning                                      |
|--------|----------------------------------------------|
| Blue   | Good performance (high AVG, low ERA/WHIP)    |
| Yellow | Warning / home run highlight                 |
| Red    | Poor performance or loss                     |
| Green  | Win result                                   |

---

## Notes

- The `rangers.db` file is excluded from version control via `.gitignore`. It is created automatically on first sync.
- All times are displayed in CDT (UTC-5).
- Innings Pitched math uses out-based arithmetic to avoid decimal errors (e.g. 6.2 + 0.1 = 7.0, not 6.3).
- Wild card position is calculated from live standings data and is an approximation — it does not account for tiebreaker rules.
