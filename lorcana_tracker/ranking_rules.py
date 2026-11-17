import sqlite3
from typing import Any

from approved_major_events import is_approved_major_event
from constants import (
    BEST_EVENT_COUNT,
    COMMUNITY_POINT_CAP,
    DB_NAME,
    EVENT_END_DATE,
    EVENT_START_DATE,
    MAX_SET_CHAMPIONSHIPS,
    MAX_DTQS,
    EVENTS_PER_COMMUNITY_POINT,
    SET_CHAMPIONSHIP_PHASE_GROUPS,
    SET_CHAMPIONSHIP_TEMPLATE_IDS,
)
from league_players import (
    get_league_player_info,
    is_league_player,
)


# Add officially designated Season 2 DTQ event IDs here.
APPROVED_DTQ_EVENT_IDS: set[int] = {
    954401,   # Oct 24 - Top Deck Keep
    879490,   # Oct 31 - On-Board Gaming
    1137263,  # Nov 1 - Top Choice Gaming
    1137279,  # Nov 8 - The Hungry Dragon
    1227366,  # Dec 12 - Grail & Grade
}


def classify_event(
    event_id: int,
    event_name: str | None,
    event_configuration_template: str | None = None,
    phase_template_group: str | None = None,
) -> str:
    """
    Classify events for Season 2 scoring.
    """

    if event_id in APPROVED_DTQ_EVENT_IDS:
        return "dtq"

    if is_approved_major_event(event_id):
        return "major"

    if (
        event_configuration_template in SET_CHAMPIONSHIP_TEMPLATE_IDS
        or phase_template_group in SET_CHAMPIONSHIP_PHASE_GROUPS
    ):
        return "set_championship"

    name = (event_name or "").lower()

    if "set championship" in name:
        return "set_championship"

    return "weekly_local"


def top_cut_bonus(
    player_count: int,
    final_place: int | None,
    has_top_cut: bool,
) -> int:
    """
    Season 2 Top Cut bonuses.

    Bonuses do not stack.
    """

    if final_place is None:
        return 0

    # Eight-player events with top cut have a special champion bonus.
    if player_count == 8:
        return 2 if has_top_cut and final_place == 1 else 0

    # Events with fewer than 8 players receive no bonus.
    if player_count < 9 or not has_top_cut:
        return 0

    if final_place == 1:
        return 6

    if final_place == 2:
        return 4

    if final_place <= 4:
        return 2

    if player_count >= 17 and final_place <= 8:
        return 1

    return 0


def event_score(
    swiss_wins: int,
    player_count: int,
    final_place: int | None = None,
    has_top_cut: bool = False,
) -> int:
    """
    Season 2 scoring for all eligible event types.

    Swiss wins and byes: 2 points each.
    Top Cut bonuses are awarded separately.
    """

    base_points = max(0, swiss_wins) * 2

    bonus = top_cut_bonus(
        player_count=player_count,
        final_place=final_place,
        has_top_cut=has_top_cut,
    )

    return base_points + bonus


def select_counted_events(
    event_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Select the player's counted Season 2 events.

    Rules:
    - Best 10 eligible scores.
    - Maximum 4 Set Championships.
    - Maximum 2 DTQs.
    - Remaining scores from Weekly Locals.

    For equal scores, Set Championships are prioritized
    because their points are a leaderboard tiebreaker.
    """

    sorted_events = sorted(
        event_scores,
        key=lambda event: (
            event["score"],
            event["event_type"] == "set_championship",
            event.get("start_date") or "",
            event["event_id"],
        ),
        reverse=True,
    )

    counted_events: list[dict[str, Any]] = []

    counted_set_championships = 0
    counted_dtqs = 0

    for event in sorted_events:

        event_type = event["event_type"]

        if event_type == "set_championship":

            if counted_set_championships >= MAX_SET_CHAMPIONSHIPS:
                continue

            counted_set_championships += 1

        elif event_type == "dtq":

            if counted_dtqs >= MAX_DTQS:
                continue

            counted_dtqs += 1

        elif event_type != "weekly_local":
            continue

        counted_events.append(event)

        if len(counted_events) >= BEST_EVENT_COUNT:
            break

    return counted_events


def get_counted_score_vector(
    counted_events: list[dict[str, Any]],
) -> tuple[int, ...]:
    """
    Return counted scores from highest to lowest,
    padded with zeroes.

    Used for Season 2 leaderboard tiebreakers.
    """

    scores = sorted(
        (event["score"] for event in counted_events),
        reverse=True,
    )

    scores.extend([0] * (BEST_EVENT_COUNT - len(scores)))

    return tuple(scores[:BEST_EVENT_COUNT])


def calculate_leaderboard() -> list[dict[str, Any]]:

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            pr.player_id,
            MAX(pr.display_name),
            pr.event_id,
            e.name,
            e.start_date,
            e.event_configuration_template,
            e.phase_template_group,
            e.starting_player_count,
            e.swiss_round_count,
            e.has_top_cut,
            pr.matches_won,
            pr.matches_lost,
            pr.matches_drawn,
            pr.swiss_wins,
            pr.swiss_losses,
            pr.swiss_draws,
            pr.swiss_place,
            pr.final_place
        FROM player_results pr
        LEFT JOIN events e
            ON pr.event_id = e.event_id
        WHERE
            e.start_date >= ?
            AND e.start_date < ?
        GROUP BY
            pr.player_id,
            pr.event_id
        """,
        (
            EVENT_START_DATE,
            EVENT_END_DATE,
        ),
    )

    rows = cur.fetchall()
    conn.close()

    # Determine actual Swiss rounds represented by each event.

    event_actual_rounds: dict[int, int] = {}

    for row in rows:

        event_id = row[2]

        wins = row[10] or 0
        losses = row[11] or 0
        draws = row[12] or 0

        swiss_wins = row[13]
        swiss_losses = row[14]
        swiss_draws = row[15]

        if swiss_wins is None:
            swiss_wins = wins

        if swiss_losses is None:
            swiss_losses = losses

        if swiss_draws is None:
            swiss_draws = draws

        actual_rounds = (
            swiss_wins
            + swiss_losses
            + swiss_draws
        )

        current_maximum = event_actual_rounds.get(event_id, 0)

        if actual_rounds > current_maximum:
            event_actual_rounds[event_id] = actual_rounds

    players: dict[int, dict[str, Any]] = {}

    for row in rows:

        (
            player_id,
            display_name,
            event_id,
            event_name,
            start_date,
            event_configuration_template,
            phase_template_group,
            starting_player_count,
            swiss_round_count,
            has_top_cut,
            wins,
            losses,
            draws,
            swiss_wins,
            swiss_losses,
            swiss_draws,
            swiss_place,
            final_place,
        ) = row

        if not is_league_player(player_id):
            continue

        event_type = classify_event(
            event_id=event_id,
            event_name=event_name,
            event_configuration_template=event_configuration_template,
            phase_template_group=phase_template_group,
        )

        # Exclude major events.
        if event_type == "major":
            continue

        # Only supported Season 2 event types count.
        if event_type not in (
            "weekly_local",
            "set_championship",
            "dtq",
        ):
            continue

        wins = wins or 0
        losses = losses or 0
        draws = draws or 0

        player_count = starting_player_count or 0
        has_top_cut = bool(has_top_cut)

        scoring_wins = (
            swiss_wins
            if swiss_wins is not None
            else wins
        )

        scoring_losses = (
            swiss_losses
            if swiss_losses is not None
            else losses
        )

        scoring_draws = (
            swiss_draws
            if swiss_draws is not None
            else draws
        )

        fallback_rounds = (
            scoring_wins
            + scoring_losses
            + scoring_draws
        )

        if has_top_cut:
            scoring_rounds = (
                swiss_round_count
                or fallback_rounds
            )
        else:
            scoring_rounds = event_actual_rounds.get(
                event_id,
                fallback_rounds,
            )

        if player_id not in players:

            player_info = get_league_player_info(player_id)

            players[player_id] = {
                "player_id": player_id,
                "league_name": player_info.get(
                    "league_name",
                    display_name,
                ),
                "event_scores": [],
                "events_played": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
            }

        player = players[player_id]

        # Only award attendance/community-point credit when
        # the player has at least one recorded match result.
        # A 0-0-0 record does not count as attendance.
        if wins + losses + draws > 0:
            player["events_played"] += 1

        player["wins"] += wins
        player["losses"] += losses
        player["draws"] += draws

        # Season 2 unified scoring.
        score = event_score(
            swiss_wins=scoring_wins,
            player_count=player_count,
            final_place=final_place,
            has_top_cut=has_top_cut,
        )

        player["event_scores"].append(
            {
                "event_id": event_id,
                "event_name": event_name,
                "event_type": event_type,
                "score": score,
                "record": f"{wins}-{losses}-{draws}",
                "swiss_record": (
                    f"{scoring_wins}-"
                    f"{scoring_losses}-"
                    f"{scoring_draws}"
                ),
                "player_count": player_count,
                "swiss_rounds": scoring_rounds,
                "has_top_cut": has_top_cut,
                "final_place": (
                    final_place
                    if final_place is not None
                    else 9999
                ),
                "start_date": start_date,
            }
        )

    leaderboard: list[dict[str, Any]] = []

    for player in players.values():

        counted_events = select_counted_events(
            player["event_scores"]
        )

        counted_event_total = sum(
            event["score"]
            for event in counted_events
        )

        # Season 2:
        # 1 Community Point per 2 eligible events.
        # Maximum 6 Community Points.
        # Zero-match records do not count toward attendance.

        community_points = min(
            player["events_played"] // EVENTS_PER_COMMUNITY_POINT,
            COMMUNITY_POINT_CAP,
        )

        total_score = (
            counted_event_total
            + community_points
        )

        counted_score_vector = get_counted_score_vector(
            counted_events
        )

        counted_set_events = [
            event
            for event in counted_events
            if event["event_type"] == "set_championship"
        ]

        counted_set_championship_points = sum(
            event["score"]
            for event in counted_set_events
        )

        counted_set_championships = len(
            counted_set_events
        )

        counted_dtqs = sum(
            1
            for event in counted_events
            if event["event_type"] == "dtq"
        )

        total_eligible_event_points = sum(
            event["score"]
            for event in player["event_scores"]
        )

        leaderboard.append(
            {
                "player_id": player["player_id"],
                "league_name": player["league_name"],
                "total_score": total_score,
                "counted_event_total": counted_event_total,

                # Legacy aliases for compatibility.
                "best_8_total": counted_event_total,

                "community_points": community_points,
                "events_played": player["events_played"],

                "record": (
                    f"{player['wins']}-"
                    f"{player['losses']}-"
                    f"{player['draws']}"
                ),

                "counted_events": counted_events,
                "best_8_events": counted_events,

                "counted_score_vector": counted_score_vector,

                "counted_set_championship_points": (
                    counted_set_championship_points
                ),

                "counted_set_championships": (
                    counted_set_championships
                ),

                "counted_dtqs": counted_dtqs,

                "total_eligible_event_points": (
                    total_eligible_event_points
                ),
            }
        )

    # Season 2 leaderboard tiebreakers:
    #
    # 1. Total Overall LSL Score.
    # 2. Highest counted event score,
    #    then next-highest, etc.
    # 3. Points from counted Set Championships.
    # 4. Total eligible events attended.
    # 5. Administrative tiebreaker if still tied.

    leaderboard.sort(
        key=lambda player: (
            player["total_score"],
            player["counted_score_vector"],
            player["counted_set_championship_points"],
            player["events_played"],
        ),
        reverse=True,
    )

    for index, player in enumerate(
        leaderboard,
        start=1,
    ):
        player["rank"] = index

    return leaderboard


def save_rankings_snapshot() -> None:

    leaderboard = calculate_leaderboard()

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS current_rankings")

    cur.execute(
        """
        CREATE TABLE current_rankings (
            rank INTEGER PRIMARY KEY,
            player_id INTEGER,
            league_name TEXT,
            total_score INTEGER,
            counted_event_total INTEGER,
            best_8_total INTEGER,
            community_points INTEGER,
            events_played INTEGER,
            record TEXT,
            highest_counted_score INTEGER,
            counted_set_championship_points INTEGER,
            counted_set_championships INTEGER,
            total_eligible_event_points INTEGER,
            calculated_at TEXT
        )
        """
    )

    for player in leaderboard:

        counted_scores = player["counted_score_vector"]

        highest_counted_score = (
            counted_scores[0]
            if counted_scores
            else 0
        )

        cur.execute(
            """
            INSERT INTO current_rankings (
                rank,
                player_id,
                league_name,
                total_score,
                counted_event_total,
                best_8_total,
                community_points,
                events_played,
                record,
                highest_counted_score,
                counted_set_championship_points,
                counted_set_championships,
                total_eligible_event_points,
                calculated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                datetime('now')
            )
            """,
            (
                player["rank"],
                player["player_id"],
                player["league_name"],
                player["total_score"],
                player["counted_event_total"],
                player["best_8_total"],
                player["community_points"],
                player["events_played"],
                player["record"],
                highest_counted_score,
                player["counted_set_championship_points"],
                player["counted_set_championships"],
                player["total_eligible_event_points"],
            ),
        )

    conn.commit()
    conn.close()

    print(
        f"Saved {len(leaderboard)} players "
        "to current_rankings."
    )


def print_top_32() -> None:

    leaderboard = calculate_leaderboard()[:32]

    print("\nLore Seekers League Top 32")
    print("--------------------------")

    if not leaderboard:
        print("No enrolled league players found.")
        return

    for player in leaderboard:

        print(
            f"{player['rank']}. "
            f"{player['league_name']}"
        )

        print(
            f"   Player ID: "
            f"{player['player_id']}"
        )

        print(
            f"   Overall LSL Score: "
            f"{player['total_score']}"
        )

        print(
            f"   Counted Event Total: "
            f"{player['counted_event_total']}"
        )

        print(
            f"   Community Points: "
            f"{player['community_points']}"
        )

        print(
            f"   Counted Set Championships: "
            f"{player['counted_set_championships']}"
        )

        print(
            f"   Counted DTQs: "
            f"{player['counted_dtqs']}"
        )

        print(
            f"   Eligible Events Played: "
            f"{player['events_played']}"
        )

        print(
            f"   Record: "
            f"{player['record']}"
        )


def print_player_ranking(
    search_text: str,
) -> None:

    leaderboard = calculate_leaderboard()
    normalized_search = search_text.strip().lower()

    for player in leaderboard:

        player_id_matches = (
            str(player["player_id"])
            == normalized_search
        )

        name_matches = (
            normalized_search
            in player["league_name"].lower()
        )

        if not player_id_matches and not name_matches:
            continue

        print(
            f"\nRanking for "
            f"{player['league_name']}"
        )

        print("--------------------------")
        print(f"Rank: {player['rank']}")

        print(
            f"Player ID: "
            f"{player['player_id']}"
        )

        print(
            f"Overall LSL Score: "
            f"{player['total_score']}"
        )

        print(
            f"Counted Event Total: "
            f"{player['counted_event_total']}"
        )

        print(
            f"Community Points: "
            f"{player['community_points']}"
        )

        print(
            "Counted Set Championship Points: "
            f"{player['counted_set_championship_points']}"
        )

        print(
            "Counted Set Championships: "
            f"{player['counted_set_championships']}"
        )

        print(
            "Counted DTQs: "
            f"{player['counted_dtqs']}"
        )

        print(
            "Total Eligible Event Points "
            "Before Cap: "
            f"{player['total_eligible_event_points']}"
        )

        print(
            f"Eligible Events Played: "
            f"{player['events_played']}"
        )

        print(f"Record: {player['record']}")

        print(
            f"\nCounted Events "
            f"(Best {BEST_EVENT_COUNT}, "
            f"Maximum {MAX_SET_CHAMPIONSHIPS} "
            f"Set Championships, {MAX_DTQS} DTQs)"
        )

        print("--------------------------")

        if not player["counted_events"]:
            print("No counted events.")
            return

        for event in player["counted_events"]:

            print(
                f"{event['score']} pts - "
                f"{event['event_name']}"
            )

            print(
                f"   Event ID: "
                f"{event['event_id']}"
            )

            print(
                f"   Type: "
                f"{event['event_type']}"
            )

            print(
                f"   Final Record: "
                f"{event['record']}"
            )

            print(
                f"   Swiss Record: "
                f"{event['swiss_record']}"
            )

            print(
                f"   Swiss Rounds: "
                f"{event['swiss_rounds']}"
            )

            print(
                "   Top Cut: "
                f"{'Yes' if event['has_top_cut'] else 'No'}"
            )

            print(
                f"   Final Place: "
                f"{event['final_place']}"
            )

            print(
                f"   Event Size: "
                f"{event['player_count']} players"
            )

        return

    print(
        "No enrolled league player found for: "
        f"{search_text}"
    )


if __name__ == "__main__":
    print_top_32()