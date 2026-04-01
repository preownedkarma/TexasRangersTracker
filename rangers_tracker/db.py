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
    venue, roof, day_night, game_time,
    weather_condition, weather_temp, weather_wind
):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO games
            (game_pk, date, opponent, result, score, rangers_side,
             venue, roof, day_night, game_time,
             weather_condition, weather_temp, weather_wind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_pk, date, opponent, result, score, rangers_side,
            venue, roof, day_night, game_time,
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
