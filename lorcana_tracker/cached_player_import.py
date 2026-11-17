
"""
Import historical player results from the local SQLite cache.

Swiss standings are preferred when available.
Registration match records are used as a fallback.

No Play Hub API requests are made by this module.
"""

import sqlite3

from constants import DB_NAME


def import_cached_players_for_event(event_id=None, player_id=None):
    """
    Import cached results for registered league players.

    Optional filters:
        event_id: import only one event
        player_id: import only one player

    Returns the number of newly inserted player results.
    """

    with sqlite3.connect(DB_NAME) as conn:
        filters = [
            "s.registrations_cached = 1",
            """(
                sw.player_id IS NOT NULL
                OR COALESCE(r.matches_won, 0)
                 + COALESCE(r.matches_lost, 0)
                 + COALESCE(r.matches_drawn, 0) > 0
            )""",
        ]

        params = []

        if event_id is not None:
            filters.append("r.event_id = ?")
            params.append(int(event_id))

        if player_id is not None:
            filters.append("r.player_id = ?")
            params.append(int(player_id))

        where_clause = " AND ".join(filters)

        before = conn.total_changes

        conn.execute(f"""
            INSERT OR IGNORE INTO player_results (
                event_id,
                store_id,
                player_id,
                display_name,
                matches_won,
                matches_lost,
                matches_drawn,
                total_match_points,
                final_place,
                captured_at,
                swiss_wins,
                swiss_losses,
                swiss_draws,
                swiss_place
            )
            SELECT
                r.event_id,
                e.store_id,
                r.player_id,
                r.display_name,
                r.matches_won,
                r.matches_lost,
                r.matches_drawn,
                r.total_match_points,
                r.final_place,
                datetime('now'),
                COALESCE(sw.swiss_wins, r.matches_won),
                COALESCE(sw.swiss_losses, r.matches_lost),
                COALESCE(sw.swiss_draws, r.matches_drawn),
                sw.swiss_place
            FROM event_registrations r
            JOIN events e
                ON e.event_id = r.event_id
            JOIN event_cache_status s
                ON s.event_id = r.event_id
            JOIN league_players lp
                ON lp.player_id = r.player_id
            LEFT JOIN event_swiss_standings sw
                ON sw.event_id = r.event_id
               AND sw.player_id = r.player_id
            WHERE {where_clause}
        """, params)

        inserted = conn.total_changes - before

        # Fill missing Swiss records in existing results.
        # Never replace verified Swiss results.
        conn.execute(f"""
            UPDATE player_results
            SET
                swiss_wins = COALESCE(
                    swiss_wins,
                    (
                        SELECT COALESCE(
                            sw.swiss_wins,
                            r.matches_won
                        )
                        FROM event_registrations r
                        LEFT JOIN event_swiss_standings sw
                          ON sw.event_id = r.event_id
                         AND sw.player_id = r.player_id
                        WHERE r.event_id = player_results.event_id
                          AND r.player_id = player_results.player_id
                    )
                ),
                swiss_losses = COALESCE(
                    swiss_losses,
                    (
                        SELECT COALESCE(
                            sw.swiss_losses,
                            r.matches_lost
                        )
                        FROM event_registrations r
                        LEFT JOIN event_swiss_standings sw
                          ON sw.event_id = r.event_id
                         AND sw.player_id = r.player_id
                        WHERE r.event_id = player_results.event_id
                          AND r.player_id = player_results.player_id
                    )
                ),
                swiss_draws = COALESCE(
                    swiss_draws,
                    (
                        SELECT COALESCE(
                            sw.swiss_draws,
                            r.matches_drawn
                        )
                        FROM event_registrations r
                        LEFT JOIN event_swiss_standings sw
                          ON sw.event_id = r.event_id
                         AND sw.player_id = r.player_id
                        WHERE r.event_id = player_results.event_id
                          AND r.player_id = player_results.player_id
                    )
                )
            WHERE EXISTS (
                SELECT 1
                FROM event_registrations r
                JOIN event_cache_status s
                  ON s.event_id = r.event_id
                WHERE r.event_id = player_results.event_id
                  AND r.player_id = player_results.player_id
                  AND s.registrations_cached = 1
                  AND (
                      COALESCE(r.matches_won, 0)
                    + COALESCE(r.matches_lost, 0)
                    + COALESCE(r.matches_drawn, 0) > 0
                    OR EXISTS (
                        SELECT 1
                        FROM event_swiss_standings sw
                        WHERE sw.event_id = r.event_id
                          AND sw.player_id = r.player_id
                    )
                  )
            )
            AND (
                swiss_wins IS NULL
                OR swiss_losses IS NULL
                OR swiss_draws IS NULL
            )
            {"AND event_id = ?" if event_id is not None else ""}
            {"AND player_id = ?" if player_id is not None else ""}
        """, params)

        return inserted


def import_all_cached_league_players():
    """Import cached results for all registered league players."""
    return import_cached_players_for_event()


def find_cached_event_player(event_id, username):
    """
    Find a player in an event's cached registrations.

    Returns a list of (player_id, display_name) tuples.
    """
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("""
            SELECT player_id, display_name
            FROM event_registrations
            WHERE event_id = ?
              AND LOWER(TRIM(display_name)) = LOWER(TRIM(?))
        """, (int(event_id), username)).fetchall()
