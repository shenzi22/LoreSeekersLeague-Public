DB_NAME = "lorcana_tracker_s2.db"

BASE_URL = (
    "https://api.cloudflare.ravensburgerplay.com/"
    "hydraproxy/api/v2"
)

GAME_SLUG = "disney-lorcana"

STORE_SEARCH_URL = (
    "https://api.cloudflare.ravensburgerplay.com/"
    "hydraproxy/api/v2/game-stores/"
    "?num_miles=175"
    "&page=1"
    "&page_size=100"
    "&latitude=33.836593199999996"
    "&longitude=-117.9143012"
    "&game_id=1"
)

SEASON_TYPE = "long"

# Season 2: October 16, 2026 at 12:00 AM Pacific (PDT)
EVENT_START_DATE = "2026-10-16T07:00:00.000Z"

# Exclusive cutoff: January 25, 2027 at 12:00 AM Pacific (PST)
# Includes all eligible events on January 24.
EVENT_END_DATE = "2027-01-25T08:00:00.000Z"

# Season 2 opt-in deadline: December 6, 2026 at 11:59 PM PST
OPT_IN_DEADLINE = "2026-12-07T07:59:00.000Z"

SEASON_SETTINGS = {
    "short": {
        "best_event_count": 8,
        "max_set_championships": 3,
        "max_dtqs": 2,
        "community_point_cap": 6,
        "events_per_community_point": 2,
    },
    "long": {
        "best_event_count": 10,
        "max_set_championships": 4,
        "max_dtqs": 2,
        "community_point_cap": 6,
        "events_per_community_point": 2,
    },
}

if SEASON_TYPE not in SEASON_SETTINGS:
    raise ValueError(
        'SEASON_TYPE must be either "short" or "long".'
    )

BEST_EVENT_COUNT = SEASON_SETTINGS[SEASON_TYPE]["best_event_count"]

MAX_SET_CHAMPIONSHIPS = (
    SEASON_SETTINGS[SEASON_TYPE]["max_set_championships"]
)

MAX_DTQS = SEASON_SETTINGS[SEASON_TYPE]["max_dtqs"]

COMMUNITY_POINT_CAP = (
    SEASON_SETTINGS[SEASON_TYPE]["community_point_cap"]
)

EVENTS_PER_COMMUNITY_POINT = (
    SEASON_SETTINGS[SEASON_TYPE]["events_per_community_point"]
)

SET_CHAMPIONSHIP_TEMPLATE_IDS = {
    "ea77d733-83d6-48ec-8ed8-274478b7dfc6"
}

SET_CHAMPIONSHIP_PHASE_GROUPS = {
    "f6a76808-5d5c-429f-8753-02d0cfc1ee03"
}