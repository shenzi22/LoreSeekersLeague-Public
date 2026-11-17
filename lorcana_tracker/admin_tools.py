import re
import requests
from urllib.parse import urlparse
from constants import BASE_URL

from approved_local_stores import add_approved_local_store
from league_players import (
    add_league_player,
    get_pending_player_imports,
    mark_player_import_processed,
    setup_league_player_tables,
)

def get_event_id_from_url(event_url):
    parsed = urlparse(event_url)
    parts = parsed.path.strip("/").split("/")

    for part in parts:
        if part.isdigit():
            return int(part)

    return None

def get_round_id_from_url(url):
    match = re.search(r"tournament-rounds/(\d+)", url)

    if match:
        return int(match.group(1))

    return None

def fetch_json(url, params=None):
    response = requests.get(url, params=params, timeout=25)
    response.raise_for_status()
    return response.json()

def fetch_all_pages(url, params=None):
    all_results = []
    page = 1

    if params is None:
        params = {}

    while True:
        params["page"] = page

        data = fetch_json(url, params)
        results = data.get("results", [])

        all_results.extend(results)

        next_page = data.get("next_page_number")

        if not next_page:
            break

        page = next_page

    return all_results

def fetch_event_details(event_id):
    url = f"{BASE_URL}/events/{event_id}/"
    return fetch_json(url)

def get_store_from_event_details(event_details):
    store = event_details.get("store", {})

    store_id = store.get("id")
    store_name = store.get("name")

    if not store_id:
        store_id = event_details.get("store_id")

    if not store_name:
        store_name = event_details.get("store_name")

    return store_id, store_name

def find_final_round_id_from_event_page(event_url):
    response = requests.get(event_url, timeout=25)
    response.raise_for_status()

    page_text = response.text

    round_matches = re.findall(
        r'\\?"id\\?":(\d+),\\?"round_number\\?":(\d+)',
        page_text
    )

    if not round_matches:
        return None

    rounds = []

    for round_id, round_number in round_matches:
        rounds.append({
            "round_id": int(round_id),
            "round_number": int(round_number),
        })

    rounds.sort(
        key=lambda item: (
            item["round_number"],
            item["round_id"]
        ),
        reverse=True
    )

    return rounds[0]["round_id"]

def fetch_standings_for_round(round_id):
    url = f"{BASE_URL}/tournament-rounds/{round_id}/standings/paginated/"

    params = {
        "page_size": 100
    }

    return fetch_all_pages(url, params)

def fetch_event_registrations(event_id):
    url = f"{BASE_URL}/events/{event_id}/registrations/"

    params = {
        "page_size": 100
    }

    return fetch_all_pages(url, params)

def find_player_in_rows(rows, search_name):
    search_name = search_name.lower()
    matches = []

    for row in rows:
        user = row.get("user", {})
        player = row.get("player", {})
        status = row.get("user_event_status", {})

        player_id = (
            user.get("id")
            or player.get("id")
            or row.get("id")
        )

        display_name = (
            user.get("best_identifier")
            or player.get("best_identifier")
            or ""
        )

        playhub_name = status.get("best_identifier") or ""

        if (
            search_name in display_name.lower()
            or search_name in playhub_name.lower()
        ):
            matches.append({
                "player_id": player_id,
                "display_name": display_name,
                "playhub_name": playhub_name,
            })

    return matches

def process_player_import_queue():
    setup_league_player_tables()

    pending_imports = get_pending_player_imports()

    if not pending_imports:
        print("No pending player imports.")
        return

    for row in pending_imports:
        import_id, event_url, search_name, league_name, region = row

        event_id = get_event_id_from_url(event_url)

        print("--------------------------------")
        print(f"Import ID: {import_id}")
        print(f"Searching for player: {search_name}")

        if event_id:
    	    print(f"Event ID: {event_id}")

        round_id = get_round_id_from_url(event_url)

        if not round_id:
            try:
                round_id = find_final_round_id_from_event_page(event_url)
            except requests.RequestException as error:
                print(f"Could not read event page for round ID: {error}")

        matches = []

        if round_id:
            print(f"Tournament Round ID: {round_id}")

            try:
                standings_rows = fetch_standings_for_round(round_id)
                matches = find_player_in_rows(
                    standings_rows,
                    search_name
                )
            except requests.HTTPError as error:
                print(f"Could not fetch standings for round {round_id}: {error}")

        if not matches and event_id:
            print("Trying event registrations as backup...")

            try:
                registrations = fetch_event_registrations(event_id)
                matches = find_player_in_rows(
                    registrations,
                    search_name
                )
            except requests.HTTPError as error:
                print(f"Could not fetch registrations for event {event_id}: {error}")

        if len(matches) == 0:
            print(f"No match found for: {search_name}")
            continue

        if len(matches) > 1:
            print(f"Multiple matches found for: {search_name}")

            for match in matches:
                found_name = (
                    match["playhub_name"]
                    or match["display_name"]
                )

                print(
                    f"  {match['player_id']} - "
                    f"{found_name}"
                )

            print("Skipping so you can make the search name more specific.")
            continue

        player = matches[0]

        found_name = (
            player["playhub_name"]
            or player["display_name"]
        )

        if not league_name:
            league_name = found_name

        add_league_player(
            player["player_id"],
            league_name,
            region
        )

        mark_player_import_processed(import_id)

        print(
            f"Processed import {import_id}: "
            f"{league_name} -> {player['player_id']} "
            f"({found_name})"
        )

if __name__ == "__main__":
    process_player_import_queue()