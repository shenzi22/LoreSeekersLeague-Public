import sqlite3
from constants import DB_NAME

def get_connection():
    return sqlite3.connect(DB_NAME)

def create_approved_major_events_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS approved_major_events (
            event_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            event_type TEXT,
            standings_url TEXT,
            day_2_start_round INTEGER
        )
    """)

    conn.commit()
    conn.close()

def seed_approved_major_events():
    create_approved_major_events_table()

    approved_events = [
        (
            352356,
            "Glimmer Games CCQ",
            "socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/602805/standings/paginated/?page=1&page_size=200",
            None,
        ),
        (
            512106,
            "Disney Lorcana Challenge: São Paulo",
            "non_socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/730447/standings/paginated/?page=1&page_size=200",
            None,
        ),
        (
            520475,
            "Vegas CCQ",
            "non_socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/728882/standings/paginated/?page=1&page_size=100",
            None,
        ),
        (
            402587,
            "Disney Lorcana Challenge - Melbourne VIC - 21st - 22nd February",
            "non_socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/494666/standings/paginated/?page=1&page_size=400",
            None,
        ),
        (
            528227,
            "ECC - Infinity $10k CCQ (Presented by Lorcana Frannn)",
            "socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/857607/standings/paginated/?page=1&page_size=200",
            7,
        ),
        (
            528253,
            "ECC - Core $3k (Presented by LorcanaFrannn)",
            "socal_side",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/856864/standings/paginated/?page=1&page_size=200",
            None,
        ),
        (
            648791,
            "Disney Lorcana Challenge: Dortmund 1",
            "non_socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/916495/standings/paginated/?page=1&page_size=600",
            9,
        ),
        (
            508677,
            "Disney Lorcana Challenge: Indianapolis",
            "non_socal_main",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/979654/standings/paginated/?page=1&page_size=2000",
            9,
        ),
        (
            602048,
            "DLC Indy - Friday 12pm - Pregame Ticket Quest - Infinity Constructed",
            "non_socal_side",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/964641/standings/paginated/?page=1&page_size=2000",
            None,
        ),
        (
            602068,
            "DLC Indy - Sun 10am - Promo Quest - Core Constructed",
            "non_socal_side",
            "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/tournament-rounds/977120/standings/paginated/?page=1&page_size=1000",
            None,
        ),
    ]

    conn = get_connection()
    cur = conn.cursor()

    cur.executemany("""
        INSERT OR REPLACE INTO approved_major_events (
            event_id,
            name,
            event_type,
            standings_url,
            day_2_start_round
        )
        VALUES (?, ?, ?, ?, ?)
    """, approved_events)

    conn.commit()
    conn.close()

def is_approved_major_event(event_id):
    seed_approved_major_events()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM approved_major_events
        WHERE event_id = ?
    """, (event_id,))

    result = cur.fetchone()
    conn.close()

    return result is not None

def get_major_event_info(event_id):
    seed_approved_major_events()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            name,
            event_type,
            standings_url,
            day_2_start_round
        FROM approved_major_events
        WHERE event_id = ?
    """, (event_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "name": row[0],
        "event_type": row[1],
        "standings_url": row[2],
        "day_2_start_round": row[3],
    }

def get_approved_major_name(event_id):
    info = get_major_event_info(event_id)

    if not info:
        return None

    return info["name"]

def get_approved_major_standings_url(event_id):
    info = get_major_event_info(event_id)

    if not info:
        return None

    return info["standings_url"]

def get_approved_major_day_2_start_round(event_id):
    info = get_major_event_info(event_id)

    if not info:
        return None

    return info["day_2_start_round"]

def get_all_approved_major_events():
    seed_approved_major_events()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            event_id,
            name,
            event_type,
            standings_url,
            day_2_start_round
        FROM approved_major_events
        ORDER BY name
    """)

    rows = cur.fetchall()
    conn.close()

    return rows