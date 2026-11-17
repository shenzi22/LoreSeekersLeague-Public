
import sqlite3
import time
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlparse, urlunparse

import requests

from approved_local_stores import get_all_approved_local_stores
from approved_major_events import is_approved_major_event
from constants import (
    BASE_URL,
    DB_NAME,
    EVENT_START_DATE,
    EVENT_END_DATE,
    GAME_SLUG,
)
from league_players import is_league_player
from ranking_rules import (
    print_player_ranking,
    print_top_32,
    save_rankings_snapshot,
)
from cached_player_import import (
    import_cached_players_for_event,
    import_all_cached_league_players,
)


REQUEST_DELAY = 0.5


def get_connection():
    return sqlite3.connect(DB_NAME, timeout=30)


def create_tables():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stores (
                store_id INTEGER PRIMARY KEY,
                store_uuid TEXT,
                name TEXT,
                email TEXT,
                captured_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY,
                store_id INTEGER,
                name TEXT,
                start_date TEXT,
                status TEXT,
                captured_at TEXT,
                event_configuration_template TEXT,
                phase_template_group TEXT,
                starting_player_count INTEGER,
                swiss_round_count INTEGER,
                last_swiss_round_id INTEGER,
                has_top_cut INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS player_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                store_id INTEGER,
                player_id INTEGER,
                display_name TEXT,
                matches_won INTEGER,
                matches_lost INTEGER,
                matches_drawn INTEGER,
                total_match_points INTEGER,
                final_place INTEGER,
                captured_at TEXT,
                made_day_2 INTEGER DEFAULT 0,
                swiss_wins INTEGER,
                swiss_losses INTEGER,
                swiss_draws INTEGER,
                swiss_place INTEGER,
                UNIQUE(event_id, player_id)
            );

            CREATE TABLE IF NOT EXISTS event_registrations (
                event_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                display_name TEXT,
                matches_won INTEGER,
                matches_lost INTEGER,
                matches_drawn INTEGER,
                total_match_points INTEGER,
                final_place INTEGER,
                PRIMARY KEY(event_id, player_id)
            );

            CREATE TABLE IF NOT EXISTS event_swiss_standings (
                event_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                swiss_wins INTEGER,
                swiss_losses INTEGER,
                swiss_draws INTEGER,
                swiss_place INTEGER,
                PRIMARY KEY(event_id, player_id)
            );

            CREATE TABLE IF NOT EXISTS event_cache_status (
                event_id INTEGER PRIMARY KEY,
                registrations_cached INTEGER DEFAULT 0,
                swiss_cached INTEGER DEFAULT 0,
                finalized INTEGER DEFAULT 0,
                cached_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_store
                ON events(store_id);

            CREATE INDEX IF NOT EXISTS idx_results_player
                ON player_results(player_id);

            CREATE INDEX IF NOT EXISTS idx_results_event
                ON player_results(event_id);

            CREATE INDEX IF NOT EXISTS idx_registrations_player
                ON event_registrations(player_id);

            CREATE INDEX IF NOT EXISTS idx_swiss_player
                ON event_swiss_standings(player_id);
        """)


def now():
    return datetime.now().isoformat(timespec="seconds")


def parse_record(value):
    if not value:
        return None, None, None

    try:
        parts = [int(x) for x in value.split("-")]
        if len(parts) != 3:
            return None, None, None
        return tuple(parts)
    except (ValueError, AttributeError):
        return None, None, None


def get_swiss_phase(event):
    for phase in event.get("tournament_phases") or []:
        if phase.get("round_type") == "SWISS":
            return phase
    return None


def get_swiss_round_count(event):
    phase = get_swiss_phase(event)
    if phase:
        return phase.get("number_of_rounds")
    return event.get("number_of_rounds")


def get_last_swiss_round_id(event):
    phase = get_swiss_phase(event)
    if not phase:
        return None

    rounds = phase.get("rounds") or []
    if not rounds:
        return None

    last = max(
        rounds,
        key=lambda r: (
            r.get("round_number") or 0,
            r.get("id") or 0,
        ),
    )
    return last.get("id")


def get_has_top_cut(event):
    return int(any(
        phase.get("round_type") == "RANKED_SINGLE_ELIMINATION"
        for phase in event.get("tournament_phases") or []
    ))


def fetch_json(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            response = requests.get(
                url, params=params, timeout=25
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = max(1, min(float(retry_after), 120))
                except (TypeError, ValueError):
                    wait = min(10 * (attempt + 1), 60)

                print(f"Rate limited. Waiting {wait}s.")
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as error:
            if attempt == retries - 1:
                raise
            wait = 2 * (attempt + 1)
            print(f"Request failed: {error}")
            time.sleep(wait)

    raise RuntimeError(f"Could not fetch {url}")


def fetch_all_pages(url, params=None):
    parsed = urlparse(url)
    clean_url = urlunparse(parsed._replace(query=""))
    merged = {
        key: value[-1]
        for key, value in parse_qs(parsed.query).items()
    }
    merged.update(params or {})

    results = []
    page = 1
    visited = set()

    while page:
        if page in visited:
            raise RuntimeError("Repeated pagination page")
        visited.add(page)

        merged["page"] = page
        data = fetch_json(clean_url, merged)

        if not isinstance(data, dict):
            raise ValueError("Unexpected API response")

        batch = data.get("results")
        if not isinstance(batch, list):
            raise ValueError("Missing results list")

        results.extend(batch)
        page = data.get("next_page_number")

        if page:
            time.sleep(REQUEST_DELAY)

    return results


def fetch_events_for_store(store_id):
    return fetch_all_pages(
        f"{BASE_URL}/events/",
        {
            "start_date_after": EVENT_START_DATE,
            "start_date_before": EVENT_END_DATE,
            "display_statuses": ["past", "inProgress"],
            "game_slug": GAME_SLUG,
            "store_id": store_id,
            "page_size": 100,
        },
    )


def fetch_event_details(event_id):
    return fetch_json(f"{BASE_URL}/events/{event_id}/")


def fetch_registrations_for_event(event_id):
    return fetch_all_pages(
        f"{BASE_URL}/events/{event_id}/registrations/",
        {"page_size": 100},
    )


def fetch_standings_for_round(round_id):
    return fetch_all_pages(
        f"{BASE_URL}/tournament-rounds/"
        f"{round_id}/standings/paginated/",
        {"page_size": 100},
    )


def save_event(store_id, event):
    event_id = event.get("id")
    if event_id is None:
        raise ValueError("Event has no ID")

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO events (
                event_id, store_id, name, start_date,
                status, captured_at,
                event_configuration_template,
                phase_template_group,
                starting_player_count,
                swiss_round_count,
                last_swiss_round_id,
                has_top_cut
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                store_id = excluded.store_id,
                name = COALESCE(excluded.name, events.name),
                start_date = COALESCE(
                    excluded.start_date, events.start_date
                ),
                status = COALESCE(
                    excluded.status, events.status
                ),
                captured_at = excluded.captured_at,
                event_configuration_template = COALESCE(
                    excluded.event_configuration_template,
                    events.event_configuration_template
                ),
                phase_template_group = COALESCE(
                    excluded.phase_template_group,
                    events.phase_template_group
                ),
                starting_player_count = COALESCE(
                    excluded.starting_player_count,
                    events.starting_player_count
                ),
                swiss_round_count = COALESCE(
                    excluded.swiss_round_count,
                    events.swiss_round_count
                ),
                last_swiss_round_id = COALESCE(
                    excluded.last_swiss_round_id,
                    events.last_swiss_round_id
                ),
                has_top_cut = MAX(
                    events.has_top_cut,
                    excluded.has_top_cut
                )
        """, (
            event_id,
            store_id,
            event.get("name") or event.get("title"),
            event.get("start_date")
                or event.get("start_datetime"),
            event.get("display_status")
                or event.get("status"),
            now(),
            event.get("event_configuration_template"),
            event.get("phase_template_group"),
            event.get("starting_player_count"),
            get_swiss_round_count(event),
            get_last_swiss_round_id(event),
            get_has_top_cut(event),
        ))


def get_saved_event(event_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT status, last_swiss_round_id
            FROM events WHERE event_id = ?
        """, (event_id,)).fetchone()


def get_cache_flags(event_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT registrations_cached, swiss_cached, finalized
            FROM event_cache_status WHERE event_id = ?
        """, (event_id,)).fetchone()

    return tuple(bool(v) for v in row) if row else (
        False, False, False
    )


def event_is_fully_cached(event_id):
    return all(get_cache_flags(event_id))


def cache_event_registrations(event_id, registrations):
    rows = []

    for registration in registrations:
        user = registration.get("user") or {}
        player_id = user.get("id")

        if player_id is None:
            continue

        rows.append((
            event_id,
            player_id,
            registration.get("best_identifier")
                or user.get("best_identifier"),
            registration.get("matches_won"),
            registration.get("matches_lost"),
            registration.get("matches_drawn"),
            registration.get("total_match_points"),
            registration.get("final_place_in_standings"),
        ))

    if not rows:
        return 0

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM event_registrations WHERE event_id = ?",
            (event_id,),
        )

        conn.executemany("""
            INSERT INTO event_registrations (
                event_id, player_id, display_name,
                matches_won, matches_lost, matches_drawn,
                total_match_points, final_place
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

        conn.execute("""
            INSERT INTO event_cache_status (
                event_id, registrations_cached,
                swiss_cached, finalized, cached_at
            )
            VALUES (?, 1, 0, 0, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                registrations_cached = 1,
                finalized = 0,
                cached_at = excluded.cached_at
        """, (event_id, now()))

    return len(rows)


def cache_event_swiss_standings(event_id, standings):
    rows = []

    for row in standings:
        player = row.get("player") or {}
        player_id = player.get("id")
        wins, losses, draws = parse_record(
            row.get("match_record")
        )

        if player_id is None or wins is None:
            continue

        rows.append((
            event_id, player_id, wins, losses,
            draws, row.get("rank"),
        ))

    if not rows:
        return 0

    with get_connection() as conn:
        conn.execute("""
            DELETE FROM event_swiss_standings
            WHERE event_id = ?
        """, (event_id,))

        conn.executemany("""
            INSERT INTO event_swiss_standings (
                event_id, player_id, swiss_wins,
                swiss_losses, swiss_draws, swiss_place
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, rows)

        conn.execute("""
            INSERT INTO event_cache_status (
                event_id, registrations_cached,
                swiss_cached, finalized, cached_at
            )
            VALUES (?, 0, 1, 0, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                swiss_cached = 1,
                finalized = 0,
                cached_at = excluded.cached_at
        """, (event_id, now()))

    return len(rows)


def save_player_result(
    store_id, event_id, player_id, display_name,
    matches_won, matches_lost, matches_drawn,
    total_match_points, final_place,
):
    if player_id is None:
        return False

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO player_results (
                event_id, store_id, player_id,
                display_name, matches_won, matches_lost,
                matches_drawn, total_match_points,
                final_place, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, player_id) DO UPDATE SET
                display_name = COALESCE(
                    excluded.display_name,
                    player_results.display_name
                ),
                matches_won = COALESCE(
                    excluded.matches_won,
                    player_results.matches_won
                ),
                matches_lost = COALESCE(
                    excluded.matches_lost,
                    player_results.matches_lost
                ),
                matches_drawn = COALESCE(
                    excluded.matches_drawn,
                    player_results.matches_drawn
                ),
                total_match_points = COALESCE(
                    excluded.total_match_points,
                    player_results.total_match_points
                ),
                final_place = COALESCE(
                    excluded.final_place,
                    player_results.final_place
                )
        """, (
            event_id, store_id, player_id, display_name,
            matches_won, matches_lost, matches_drawn,
            total_match_points, final_place, now(),
        ))

    return True


def save_registration_result(store_id, event_id, registration):
    user = registration.get("user") or {}
    player_id = user.get("id")

    if not is_league_player(player_id):
        return False

    return save_player_result(
        store_id,
        event_id,
        player_id,
        registration.get("best_identifier")
            or user.get("best_identifier"),
        registration.get("matches_won"),
        registration.get("matches_lost"),
        registration.get("matches_drawn"),
        registration.get("total_match_points"),
        registration.get("final_place_in_standings"),
    )


def update_swiss_result(event_id, row):
    player = row.get("player") or {}
    player_id = player.get("id")

    if not is_league_player(player_id):
        return False

    wins, losses, draws = parse_record(
        row.get("match_record")
    )
    if wins is None:
        return False

    with get_connection() as conn:
        result = conn.execute("""
            UPDATE player_results
            SET swiss_wins = ?, swiss_losses = ?,
                swiss_draws = ?, swiss_place = ?
            WHERE event_id = ? AND player_id = ?
        """, (
            wins, losses, draws,
            row.get("rank"), event_id, player_id,
        ))

    return result.rowcount > 0


def finalize_cached_event(event_id):
    with get_connection() as conn:
        result = conn.execute("""
            UPDATE event_cache_status
            SET finalized = 1
            WHERE event_id = ?
              AND registrations_cached = 1
              AND swiss_cached = 1
              AND EXISTS (
                  SELECT 1 FROM events
                  WHERE events.event_id =
                      event_cache_status.event_id
                    AND LOWER(events.status) IN ('past', 'complete')
                    AND events.last_swiss_round_id IS NOT NULL
              )
        """, (event_id,))

    return result.rowcount > 0


def sync_cached_league_results(event_id):
    """Sync cached records into rankings, even without Swiss standings.

    Only registration records with played matches are eligible for fallback.
    For events with top cut, do not mistake overall records for Swiss records.
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT r.player_id, e.store_id, r.display_name,
                   r.matches_won, r.matches_lost, r.matches_drawn,
                   r.total_match_points, r.final_place,
                   sw.swiss_wins, sw.swiss_losses, sw.swiss_draws,
                   sw.swiss_place, COALESCE(e.has_top_cut, 0)
            FROM event_registrations r
            JOIN events e ON e.event_id = r.event_id
            JOIN league_players lp ON lp.player_id = r.player_id
            LEFT JOIN event_swiss_standings sw
              ON sw.event_id = r.event_id AND sw.player_id = r.player_id
            WHERE r.event_id = ?
        """, (event_id,)).fetchall()
        changed = 0
        for (player_id, store_id, name, wins, losses, draws,
             points, place, sw_w, sw_l, sw_d, sw_place, has_cut) in rows:
            played = sum(int(v or 0) for v in (wins, losses, draws))
            verified_swiss = all(v is not None for v in (sw_w, sw_l, sw_d))
            if not verified_swiss and (played == 0 or has_cut):
                continue
            swiss = (sw_w, sw_l, sw_d) if verified_swiss else (wins, losses, draws)
            # No unverified top-cut place/bonuses for fallback-only events.
            safe_place = place if verified_swiss else None
            result = conn.execute("""
                INSERT INTO player_results (
                    event_id, store_id, player_id, display_name,
                    matches_won, matches_lost, matches_drawn,
                    total_match_points, final_place, captured_at,
                    swiss_wins, swiss_losses, swiss_draws, swiss_place
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, player_id) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, player_results.display_name),
                    matches_won = excluded.matches_won,
                    matches_lost = excluded.matches_lost,
                    matches_drawn = excluded.matches_drawn,
                    total_match_points = excluded.total_match_points,
                    final_place = COALESCE(excluded.final_place, player_results.final_place),
                    swiss_wins = excluded.swiss_wins,
                    swiss_losses = excluded.swiss_losses,
                    swiss_draws = excluded.swiss_draws,
                    swiss_place = COALESCE(excluded.swiss_place, player_results.swiss_place)
            """, (
                event_id, store_id, player_id, name,
                wins, losses, draws, points, safe_place, now(),
                *swiss, sw_place if verified_swiss else None,
            ))
            changed += result.rowcount
    return changed


def cache_and_import_event(event_id, refresh=False):
    reg_cached, swiss_cached, finalized = get_cache_flags(event_id)
    if finalized and not refresh:
        return True

    if refresh or not reg_cached:
        registrations = fetch_registrations_for_event(event_id)
        if registrations:
            count = cache_event_registrations(event_id, registrations)
            print(f"  {event_id}: cached {count} registrations")
        else:
            print(f"  {event_id}: no registrations available")

    saved = get_saved_event(event_id)
    round_id = saved[1] if saved else None
    if round_id and (refresh or not swiss_cached):
        standings = fetch_standings_for_round(round_id)
        if standings:
            count = cache_event_swiss_standings(event_id, standings)
            print(f"  {event_id}: cached {count} Swiss records")
        else:
            print(f"  {event_id}: Swiss standings unavailable; using eligible registration records")
    elif not round_id:
        print(f"  {event_id}: no Swiss round ID; using eligible registration records")

    # Crucially, this runs even when Swiss standings are unavailable.
    synced = sync_cached_league_results(event_id)
    if synced:
        print(f"  {event_id}: synced {synced} league-player records")

    if finalize_cached_event(event_id):
        print(f"  {event_id}: finalized")
    return event_is_fully_cached(event_id)


def crawl_store_events(historical=False):
    approved_stores = get_all_approved_local_stores()

    print(
        f"Scanning {len(approved_stores)} approved stores. "
        f"Historical mode: {historical}"
    )

    processed = 0
    skipped = 0
    failed = 0

    for store_id, store_name, region in approved_stores:
        print(f"\nStore: {store_name} ({store_id})")

        try:
            events = fetch_events_for_store(store_id)
        except (requests.RequestException, RuntimeError) as error:
            print(f"  Store listing failed: {error}")
            failed += 1
            continue

        for event in events:
            event_id = event.get("id")

            if not event_id:
                continue

            if is_approved_major_event(event_id):
                continue

            if str(event.get("display_status") or event.get("status") or "").lower() in {"canceled", "cancelled"}:
                skipped += 1
                continue

            if event_is_fully_cached(event_id):
                skipped += 1
                continue

            saved = get_saved_event(event_id)

            listed_status = str(
                event.get("display_status")
                or event.get("status")
                or ""
            ).lower()

            in_progress = listed_status in {
                "inprogress", "in_progress"
            }

            # Normal crawls do not backfill old saved events.
            if (
                not historical
                and saved is not None
                and not in_progress
                and get_cache_flags(event_id)[0]
            ):
                skipped += 1
                continue

            try:
                # Refresh metadata for new and ongoing events.
                if (
                    saved is None
                    or in_progress
                    or saved[1] is None
                ):
                    details = fetch_event_details(event_id)
                    save_event(store_id, details)

                elif listed_status == "past":
                    with get_connection() as conn:
                        conn.execute("""
                            UPDATE events SET status = 'past'
                            WHERE event_id = ?
                        """, (event_id,))

                complete = cache_and_import_event(
                    event_id,
                    refresh=in_progress,
                )

                processed += 1

                print(
                    f"  {event_id}: "
                    f"{'complete' if complete else 'pending'}"
                )

            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                KeyError,
                sqlite3.Error,
            ) as error:
                failed += 1
                print(f"  {event_id}: ERROR: {error}")

            time.sleep(REQUEST_DELAY)

    # Each processed event is synchronized above. Do not run the generic
    # importer here: it cannot verify top-cut fallback records.
    imported = 0

    print("\nCrawl finished.")
    print(f"Processed: {processed}")
    print(f"Skipped: {skipped}")
    print(f"Failures: {failed}")
    print(f"New cached player results imported: {imported}")


def update_database(historical=False):
    create_tables()
    crawl_store_events(historical=historical)


def search_player(search_text):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT player_id, display_name, event_id,
                   store_id, matches_won, matches_lost,
                   matches_drawn, swiss_wins, swiss_losses,
                   swiss_draws, total_match_points,
                   final_place
            FROM player_results
            WHERE CAST(player_id AS TEXT) LIKE ?
               OR LOWER(display_name) LIKE LOWER(?)
            ORDER BY event_id DESC
        """, (
            f"%{search_text}%",
            f"%{search_text}%",
        )).fetchall()

    if not rows:
        print("No player found.")
        return

    for row in rows:
        (
            player_id, display_name, event_id, store_id,
            won, lost, drawn, swiss_wins,
            swiss_losses, swiss_draws, points, place,
        ) = row

        print("--------------------------------")
        print(f"Player ID: {player_id}")
        print(f"Display Name: {display_name}")
        print(f"Store ID: {store_id}")
        print(f"Event ID: {event_id}")
        print(f"Final Record: {won}-{lost}-{drawn}")
        print(
            f"Swiss Record: "
            f"{swiss_wins}-{swiss_losses}-{swiss_draws}"
        )
        print(f"Match Points: {points}")
        print(f"Place: {place}")


def main():
    historical = "--historical" in sys.argv

    update_database(historical=historical)
    save_rankings_snapshot()
    print_top_32()

    while True:
        command = input(
            "\nType top32, rank NAME/ID, "
            "search NAME/ID, or quit: "
        ).strip()

        lower = command.lower()

        if lower == "quit":
            break
        elif lower in {"top32", "top10"}:
            print_top_32()
        elif lower.startswith("rank "):
            print_player_ranking(command[5:].strip())
        elif lower.startswith("search "):
            search_player(command[7:].strip())
        else:
            print("Unknown command.")


if __name__ == "__main__":
    main()
