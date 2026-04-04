"""
db.py — SQLite schema and helper functions for the Rangers Tracker.
DB file lives alongside this module at rangers_tracker/rangers.db.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "rangers.db")


def get_conn():
    """Return a sqlite3 connection with row_factory set to Row."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they do not already exist."""
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_pk       INTEGER PRIMARY KEY,
            date          TEXT,
            opponent      TEXT,
            result        TEXT,
            score         TEXT,
            rangers_side  TEXT,
            venue         TEXT,
            roof          TEXT,
            roof_status   TEXT,
            day_night     TEXT,
            game_time     TEXT,
            weather_condition TEXT,
            weather_temp      TEXT,
            weather_wind      TEXT
        );

        CREATE TABLE IF NOT EXISTS batter_lines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk     INTEGER,
            player_id   INTEGER,
            player_name TEXT,
            ab          INTEGER,
            h           INTEGER,
            hr          INTEGER,
            rbi         INTEGER,
            bb          INTEGER,
            so          INTEGER,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS pitcher_lines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk     INTEGER,
            player_id   INTEGER,
            player_name TEXT,
            ip_str      TEXT,
            h           INTEGER,
            er          INTEGER,
            bb          INTEGER,
            so          INTEGER,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );
    """)

    # Migration: add roof_status column to existing DBs that predate it
    try:
        c.execute("ALTER TABLE games ADD COLUMN roof_status TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    conn.commit()
    conn.close()
    _backfill_roof_status()


def _backfill_roof_status():
    """
    Compute roof_status for any rows where it is NULL, using already-stored
    roof type and weather columns.  Safe to call repeatedly — skips rows that
    already have a value.
    """
    # Import here to avoid a circular import (sync imports db)
    from sync import infer_roof_status

    conn = get_conn()
    rows = conn.execute(
        "SELECT game_pk, roof, weather_condition, weather_wind "
        "FROM games WHERE roof_status IS NULL"
    ).fetchall()

    for row in rows:
        status = infer_roof_status(
            row["roof"]              or "Open Air",
            row["weather_condition"] or "",
            row["weather_wind"]      or "",
        )
        conn.execute(
            "UPDATE games SET roof_status = ? WHERE game_pk = ?",
            (status, row["game_pk"]),
        )

    conn.commit()
    conn.close()


def game_exists(game_pk):
    """Return True if the game is already in the DB."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM games WHERE game_pk = ?", (game_pk,)
    ).fetchone()
    conn.close()
    return row is not None


def insert_game(
    game_pk, date, opponent, result, score, rangers_side,
    venue, roof, roof_status, day_night, game_time,
    weather_condition, weather_temp, weather_wind
):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO games
            (game_pk, date, opponent, result, score, rangers_side,
             venue, roof, roof_status, day_night, game_time,
             weather_condition, weather_temp, weather_wind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_pk, date, opponent, result, score, rangers_side,
            venue, roof, roof_status, day_night, game_time,
            weather_condition, weather_temp, weather_wind,
        ),
    )
    conn.commit()
    conn.close()


def insert_batter_line(game_pk, player_id, player_name, ab, h, hr, rbi, bb, so):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO batter_lines
            (game_pk, player_id, player_name, ab, h, hr, rbi, bb, so)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (game_pk, player_id, player_name, ab, h, hr, rbi, bb, so),
    )
    conn.commit()
    conn.close()


def insert_pitcher_line(game_pk, player_id, player_name, ip_str, h, er, bb, so):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO pitcher_lines
            (game_pk, player_id, player_name, ip_str, h, er, bb, so)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (game_pk, player_id, player_name, ip_str, h, er, bb, so),
    )
    conn.commit()
    conn.close()
