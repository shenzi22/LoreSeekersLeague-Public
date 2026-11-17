import sqlite3
from constants import DB_NAME

def get_connection():
    return sqlite3.connect(DB_NAME)


def create_approved_local_stores_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS approved_local_stores (
            store_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT
        )
    """)

    conn.commit()
    conn.close()


def seed_approved_local_stores():
    """
    Ensure the approved stores table exists.

    Season 2 stores are imported separately
    from the official store directory.
    """
    create_approved_local_stores_table()

def add_approved_local_store(store_id, name, region="SoCal"):
    seed_approved_local_stores()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO approved_local_stores (
            store_id,
            name,
            region
        )
        VALUES (?, ?, ?)
    """, (
        store_id,
        name,
        region
    ))

    conn.commit()
    conn.close()

    print(f"Approved store saved: {name} ({store_id})")


def is_approved_local_store(store_id):
    seed_approved_local_stores()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM approved_local_stores
        WHERE store_id = ?
    """, (store_id,))

    result = cur.fetchone()
    conn.close()

    return result is not None


def get_approved_local_store_name(store_id):
    seed_approved_local_stores()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT name
        FROM approved_local_stores
        WHERE store_id = ?
    """, (store_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return row[0]


def get_all_approved_local_stores():
    seed_approved_local_stores()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT store_id, name, region
        FROM approved_local_stores
        ORDER BY name
    """)

    rows = cur.fetchall()
    conn.close()

    return rows