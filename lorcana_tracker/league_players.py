import sqlite3
from constants import DB_NAME

def get_connection():
    return sqlite3.connect(DB_NAME)

def create_league_players_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_players (
            player_id INTEGER PRIMARY KEY,
            league_name TEXT NOT NULL,
            region TEXT
        )
    """)

    conn.commit()
    conn.close()

def create_player_import_queue_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_import_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_url TEXT NOT NULL,
            search_name TEXT NOT NULL,
            league_name TEXT,
            region TEXT DEFAULT 'SoCal',
            processed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def seed_league_players():
    create_league_players_table()

def setup_league_player_tables():
    seed_league_players()
    create_player_import_queue_table()

def add_league_player(player_id, league_name, region="SoCal"):
    seed_league_players()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO league_players (
            player_id,
            league_name,
            region
        )
        VALUES (?, ?, ?)
    """, (
        player_id,
        league_name,
        region
    ))

    conn.commit()
    conn.close()

    print(f"League player saved: {league_name} ({player_id})")

def add_player_import_request(
    event_url,
    search_name,
    league_name=None,
    region="SoCal"
):
    create_player_import_queue_table()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO player_import_queue (
            event_url,
            search_name,
            league_name,
            region
        )
        VALUES (?, ?, ?, ?)
    """, (
        event_url,
        search_name,
        league_name,
        region
    ))

    conn.commit()
    conn.close()

    print(f"Queued player import: {search_name}")

def get_pending_player_imports():
    create_player_import_queue_table()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            event_url,
            search_name,
            league_name,
            region
        FROM player_import_queue
        WHERE processed = 0
        ORDER BY id
    """)

    rows = cur.fetchall()
    conn.close()

    return rows

def mark_player_import_processed(import_id):
    create_player_import_queue_table()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE player_import_queue
        SET
            processed = 1,
            processed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (import_id,))

    conn.commit()
    conn.close()

def is_league_player(player_id):
    seed_league_players()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM league_players
        WHERE player_id = ?
    """, (player_id,))

    result = cur.fetchone()
    conn.close()

    return result is not None

def get_league_player_info(player_id):
    seed_league_players()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT league_name, region
        FROM league_players
        WHERE player_id = ?
    """, (player_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "league_name": row[0],
        "region": row[1],
    }

def get_all_league_players():
    seed_league_players()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT player_id, league_name, region
        FROM league_players
        ORDER BY league_name
    """)

    rows = cur.fetchall()
    conn.close()

    return rows