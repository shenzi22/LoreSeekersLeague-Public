
import os
import time
import asyncio
import csv
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from constants import DB_NAME
from lorcana_tracker import create_tables, update_database
from ranking_rules import (
    calculate_leaderboard,
    save_rankings_snapshot,
)
from cached_player_import import (
    import_cached_players_for_event,
    find_cached_event_player,
)
from admin_tools import (
    fetch_event_details,
    get_store_from_event_details,
    get_event_id_from_url,
    fetch_event_registrations,
)
from approved_local_stores import (
    add_approved_local_store,
    is_approved_local_store,
)
from league_players import (
    add_league_player,
    get_league_player_info,
    setup_league_player_tables,
)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_BOT_TOKEN was not found in the .env file."
    )

# Only this Discord role has administrative access.
# Old DISCORD_ALLOWED_ROLE_IDS values are intentionally ignored.
ADMIN_ROLE_ID = 1501336509759098977

LEADERBOARD_CACHE_SECONDS = 30.0
PACIFIC_TIME = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------
# Weekly rank usage tracking
# ---------------------------------------------------------

def current_rank_week():
    now = datetime.now(PACIFIC_TIME)
    monday = now.date() - timedelta(days=now.weekday())
    return monday.isoformat()


def setup_rank_usage_table():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discord_rank_usage (
                discord_user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                PRIMARY KEY (discord_user_id, week_start)
            )
        """)


def has_used_weekly_rank(discord_user_id):
    week_start = current_rank_week()

    with sqlite3.connect(DB_NAME) as conn:
        result = conn.execute(
            """
            SELECT 1
            FROM discord_rank_usage
            WHERE discord_user_id = ?
              AND week_start = ?
            """,
            (discord_user_id, week_start),
        ).fetchone()

    return result is not None


def record_weekly_rank(discord_user_id):
    week_start = current_rank_week()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO discord_rank_usage (
                discord_user_id,
                week_start
            )
            VALUES (?, ?)
            """,
            (discord_user_id, week_start),
        )

        return cursor.rowcount == 1


# ---------------------------------------------------------
# Bot setup
# ---------------------------------------------------------

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

_leaderboard_cache = None
_leaderboard_cache_time = 0.0

crawl_task = None
crawl_started_at = None
crawl_finished_at = None
crawl_error = None

# One lock per Discord user prevents simultaneous
# requests from bypassing the weekly limit.
rank_user_locks = {}


def get_rank_user_lock(discord_user_id):
    if discord_user_id not in rank_user_locks:
        rank_user_locks[discord_user_id] = asyncio.Lock()

    return rank_user_locks[discord_user_id]


# ---------------------------------------------------------
# Leaderboard cache
# ---------------------------------------------------------

def invalidate_leaderboard_cache():
    global _leaderboard_cache
    global _leaderboard_cache_time

    _leaderboard_cache = None
    _leaderboard_cache_time = 0.0


def get_leaderboard():
    global _leaderboard_cache
    global _leaderboard_cache_time

    current_time = time.monotonic()

    if (
        _leaderboard_cache is not None
        and current_time - _leaderboard_cache_time
        < LEADERBOARD_CACHE_SECONDS
    ):
        return _leaderboard_cache

    _leaderboard_cache = calculate_leaderboard()
    _leaderboard_cache_time = current_time

    return _leaderboard_cache


def find_players(search_text):
    search_text = search_text.strip().lower()[:100]

    if not search_text:
        return []

    leaderboard = get_leaderboard()

    exact_id_matches = [
        player
        for player in leaderboard
        if str(player["player_id"]) == search_text
    ]

    if exact_id_matches:
        return exact_id_matches

    return [
        player
        for player in leaderboard
        if search_text in player["league_name"].lower()
    ]


def find_player_by_id(player_id):
    for player in get_leaderboard():
        if str(player["player_id"]) == str(player_id):
            return player

    return None


# ---------------------------------------------------------
# Permissions
# ---------------------------------------------------------

def has_allowed_role(interaction: discord.Interaction):
    if interaction.guild is None:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id == ADMIN_ROLE_ID
        for role in member.roles
    )


# ---------------------------------------------------------
# Startup
# ---------------------------------------------------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    setup_rank_usage_table()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as error:
        print(f"Slash command sync failed: {error}")


# ---------------------------------------------------------
# /rank
# ---------------------------------------------------------

@bot.tree.command(
    name="rank",
    description="View an LSL player's ranking and point breakdown.",
)
@app_commands.describe(
    player="League name or Ravensburger player ID"
)
@app_commands.guild_only()
async def rank_command(
    interaction: discord.Interaction,
    player: str,
):
    # Admins can search without any weekly restriction.
    if has_allowed_role(interaction):
        await send_rank_response(interaction, player)
        return

    user_id = interaction.user.id
    lock = get_rank_user_lock(user_id)

    # Keep the lock until the response is delivered
    # and the successful search is recorded.
    async with lock:
        if has_used_weekly_rank(user_id):
            await interaction.response.send_message(
                "You've already used your weekly /rank search. "
                "Your next search is available Monday "
                "at 12:00 AM Pacific Time.",
                ephemeral=True,
            )
            return

        success = await send_rank_response(
            interaction,
            player,
        )

        if success:
            record_weekly_rank(user_id)


async def send_rank_response(
    interaction: discord.Interaction,
    player: str,
):
    await interaction.response.defer(ephemeral=True)

    matches = await asyncio.to_thread(
        find_players,
        player,
    )

    # An unsuccessful search does not consume the allowance.
    if not matches:
        await interaction.followup.send(
            f"No LSL player found matching **{player}**.",
            ephemeral=True,
        )
        return False

    # Ambiguous searches also do not consume the allowance.
    if len(matches) > 1:
        names = "\n".join(
            f"• {match['league_name']} "
            f"(ID {match['player_id']})"
            for match in matches[:10]
        )

        await interaction.followup.send(
            "Multiple players matched:\n\n"
            f"{names}\n\n"
            "Try the full league name or player ID.",
            ephemeral=True,
        )
        return False

    result = matches[0]

    embed = discord.Embed(
        title=(
            f"#{result['rank']} "
            f"{result['league_name']}"
        ),
        description=(
            f"Player ID: `{result['player_id']}`"
        ),
    )

    embed.add_field(
        name="Overall LSL Score",
        value=str(result["total_score"]),
        inline=True,
    )

    embed.add_field(
        name="Counted Event Total",
        value=str(result["counted_event_total"]),
        inline=True,
    )

    embed.add_field(
        name="Community Points",
        value=str(result["community_points"]),
        inline=True,
    )

    embed.add_field(
        name="Record",
        value=result["record"],
        inline=True,
    )

    embed.add_field(
        name="Eligible Events",
        value=str(result["events_played"]),
        inline=True,
    )

    embed.add_field(
        name="Counted Set Championships",
        value=str(result["counted_set_championships"]),
        inline=True,
    )

    embed.add_field(
        name="Counted DTQs",
        value=str(result["counted_dtqs"]),
        inline=True,
    )

    embed.add_field(
        name="Counted Set Championship Points",
        value=str(
            result["counted_set_championship_points"]
        ),
        inline=True,
    )

    embed.add_field(
        name="Total Eligible Event Points",
        value=str(
            result["total_eligible_event_points"]
        ),
        inline=True,
    )

    counted_events = result["counted_events"]

    if counted_events:
        event_lines = []

        for event in counted_events:
            final_place = event.get("final_place")

            place_text = (
                "N/A"
                if final_place in (None, 9999)
                else str(final_place)
            )

            event_lines.append(
                f"**{event['score']} pts** — "
                f"{event['event_name']}\n"
                f"`{event['swiss_record']}` Swiss • "
                f"Place {place_text}"
            )

        chunks = []
        current_chunk = ""

        for event_text in event_lines:
            candidate = (
                current_chunk
                + ("\n\n" if current_chunk else "")
                + event_text
            )

            if len(candidate) > 1000:
                if current_chunk:
                    chunks.append(current_chunk)

                current_chunk = event_text
            else:
                current_chunk = candidate

        if current_chunk:
            chunks.append(current_chunk)

        for index, chunk in enumerate(chunks, start=1):
            field_name = (
                "Counted Events"
                if index == 1
                else "Counted Events (continued)"
            )

            embed.add_field(
                name=field_name,
                value=chunk,
                inline=False,
            )

    # Record usage only if Discord accepts the ranking response.
    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )

    return True


# ---------------------------------------------------------
# /downloadrankings
# ---------------------------------------------------------

@bot.tree.command(
    name="downloadrankings",
    description="Download the latest LSL rankings CSV.",
)
@app_commands.guild_only()
@app_commands.check(has_allowed_role)
async def downloadrankings_command(
    interaction: discord.Interaction,
):
    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "rankings_s2.csv",
    )

    if not os.path.isfile(csv_path):
        await interaction.response.send_message(
            "No rankings CSV is available yet. "
            "An admin must complete a crawl first.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "Here are the latest LSL rankings.",
        file=discord.File(
            csv_path,
            filename="rankings_s2.csv",
        ),
        ephemeral=True,
    )


# ---------------------------------------------------------
# Cached player lookup
# ---------------------------------------------------------

def resolve_player_from_event(event_id, username):
    """
    Search the local registration cache first.

    If the event has not been cached, fetch registrations
    from Play Hub to identify the player.

    Returns:
        (player_id, playhub_name, source)
        or None

    Raises ValueError for ambiguous matches.
    """

    username = username.strip()

    if not username:
        return None

    cached_matches = find_cached_event_player(
        event_id,
        username,
    )

    if cached_matches:
        unique_matches = {
            int(player_id): display_name
            for player_id, display_name in cached_matches
        }

        if len(unique_matches) != 1:
            raise ValueError(
                "Multiple cached players matched that username."
            )

        player_id, playhub_name = next(
            iter(unique_matches.items())
        )

        return (
            player_id,
            playhub_name or username,
            "SQLite cache",
        )

    # Fallback: use Play Hub for an uncached source event.
    registrations = fetch_event_registrations(event_id)

    matches = {}

    for row in registrations:
        user = row.get("user") or {}

        player_id = user.get("id")

        playhub_name = (
            row.get("best_identifier")
            or user.get("best_identifier")
            or ""
        )

        if (
            player_id is not None
            and playhub_name.strip().casefold()
            == username.casefold()
        ):
            matches[int(player_id)] = playhub_name

    if not matches:
        return None

    if len(matches) != 1:
        raise ValueError(
            "Multiple players matched. "
            "Verify the username and event."
        )

    player_id, playhub_name = next(
        iter(matches.items())
    )

    return player_id, playhub_name, "Play Hub"


def register_and_rank_player(
    player_id,
    display_name,
):
    """
    Add a player, import their historical results
    from SQLite, and calculate their ranking.

    This does not crawl historical Play Hub events.
    """

    create_tables()
    setup_league_player_tables()

    existing = get_league_player_info(player_id)

    if existing:
        return {
            "already_registered": True,
            "existing_name": existing["league_name"],
            "imported": 0,
            "ranking": None,
        }

    add_league_player(
        player_id,
        display_name,
        "SoCal",
    )

    # Import cached tournament history.
    imported = import_cached_players_for_event(
        player_id=player_id,
    )

    # Calculate rankings with the newly added player.
    invalidate_leaderboard_cache()

    save_rankings_snapshot()

    ranking = find_player_by_id(player_id)

    return {
        "already_registered": False,
        "existing_name": None,
        "imported": imported,
        "ranking": ranking,
    }


# ---------------------------------------------------------
# /addplayer
# ---------------------------------------------------------

@bot.tree.command(
    name="addplayer",
    description="Add a league player using a Play Hub event.",
)
@app_commands.describe(
    username="Exact Play Hub username",
    event_url="Play Hub event URL",
    league_name="Optional league display name",
)
@app_commands.guild_only()
@app_commands.check(has_allowed_role)
async def addplayer_command(
    interaction: discord.Interaction,
    username: str,
    event_url: str,
    league_name: str = None,
):
    await interaction.response.defer(ephemeral=True)

    event_id = get_event_id_from_url(event_url)

    if not event_id:
        await interaction.followup.send(
            "Invalid Play Hub event URL.",
            ephemeral=True,
        )
        return

    try:
        resolved = await asyncio.to_thread(
            resolve_player_from_event,
            event_id,
            username,
        )

        if resolved is None:
            await interaction.followup.send(
                f"No exact match for **{username}** "
                f"in event `{event_id}`.",
                ephemeral=True,
            )
            return

        player_id, playhub_name, source = resolved

        display_name = (
            league_name.strip()
            if league_name and league_name.strip()
            else playhub_name
        )

        result = await asyncio.to_thread(
            register_and_rank_player,
            player_id,
            display_name,
        )

        if result["already_registered"]:
            await interaction.followup.send(
                "Player already registered:\n"
                f"**{result['existing_name']}** "
                f"(ID `{player_id}`).",
                ephemeral=True,
            )
            return

        ranking = result["ranking"]
        imported = result["imported"]

        if ranking:
            rank_text = (
                f"**Rank:** #{ranking['rank']}\n"
                f"**Overall LSL Score:** "
                f"{ranking['total_score']}\n"
                f"**Eligible Events:** "
                f"{ranking['events_played']}\n"
                f"**Record:** {ranking['record']}"
            )
        else:
            rank_text = (
                "**Rank:** Not ranked yet\n"
                "No eligible tournament results were "
                "found in the local cache."
            )

        await interaction.followup.send(
            "**Player added successfully!**\n\n"
            f"**League name:** {display_name}\n"
            f"**Play Hub name:** {playhub_name}\n"
            f"**Player ID:** `{player_id}`\n"
            f"**Source event:** `{event_id}`\n"
            f"**Player lookup:** {source}\n"
            f"**Historical results imported:** "
            f"{imported}\n\n"
            f"{rank_text}",
            ephemeral=True,
        )

    except ValueError as error:
        await interaction.followup.send(
            str(error),
            ephemeral=True,
        )

    except Exception as error:
        print(f"/addplayer error: {error!r}")

        await interaction.followup.send(
            "Unable to complete player registration. "
            "Check the bot console for details.",
            ephemeral=True,
        )


# ---------------------------------------------------------
# /addstore
# ---------------------------------------------------------

@bot.tree.command(
    name="addstore",
    description="Approve a store using a Play Hub event URL.",
)
@app_commands.describe(
    event_url="Play Hub event URL from the store",
)
@app_commands.guild_only()
@app_commands.check(has_allowed_role)
async def addstore_command(
    interaction: discord.Interaction,
    event_url: str,
):
    await interaction.response.defer(ephemeral=True)

    event_id = get_event_id_from_url(event_url)

    if not event_id:
        await interaction.followup.send(
            "Invalid Play Hub event URL.",
            ephemeral=True,
        )
        return

    try:
        event = await asyncio.to_thread(
            fetch_event_details,
            event_id,
        )

        store_id, store_name = (
            get_store_from_event_details(event)
        )

        if not store_id or not store_name:
            await interaction.followup.send(
                "Could not identify the store for this event.",
                ephemeral=True,
            )
            return

        store_id = int(store_id)

        if await asyncio.to_thread(
            is_approved_local_store,
            store_id,
        ):
            await interaction.followup.send(
                f"Store already approved: **{store_name}** "
                f"(ID `{store_id}`).",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            add_approved_local_store,
            store_id,
            store_name,
            "SoCal",
        )

        await interaction.followup.send(
            "**Store approved successfully!**\n"
            f"**Store:** {store_name}\n"
            f"**Store ID:** `{store_id}`\n"
            f"**Source event:** `{event_id}`",
            ephemeral=True,
        )

    except Exception as error:
        print(f"/addstore error: {error!r}")

        await interaction.followup.send(
            "Unable to approve store. "
            "Check the bot console for details.",
            ephemeral=True,
        )


# ---------------------------------------------------------
# Crawl management
# ---------------------------------------------------------

def export_rankings_csv():
    output_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "rankings_s2.csv",
    )

    conn = sqlite3.connect(DB_NAME)

    try:
        cursor = conn.execute(
            "SELECT * FROM current_rankings ORDER BY rank ASC"
        )

        columns = [
            description[0]
            for description in cursor.description
        ]

        rows = cursor.fetchall()

        with open(
            output_file,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            writer.writerows(rows)

        print(
            f"Exported {len(rows)} rankings to {output_file}"
        )

    finally:
        conn.close()


async def run_crawl():
    global crawl_started_at
    global crawl_finished_at
    global crawl_error

    crawl_started_at = datetime.now()
    crawl_finished_at = None
    crawl_error = None

    try:
        await asyncio.to_thread(update_database)

        await asyncio.to_thread(
            save_rankings_snapshot
        )

        await asyncio.to_thread(
            export_rankings_csv
        )

        invalidate_leaderboard_cache()

        print("Discord crawl completed successfully.")

    except Exception as error:
        crawl_error = str(error)

        print(
            f"Discord crawl failed: {error!r}"
        )

    finally:
        crawl_finished_at = datetime.now()


# ---------------------------------------------------------
# /crawl
# ---------------------------------------------------------

@bot.tree.command(
    name="crawl",
    description="Update Season 2 tournament results.",
)
@app_commands.guild_only()
@app_commands.check(has_allowed_role)
async def crawl_command(
    interaction: discord.Interaction,
):
    global crawl_task

    if crawl_task is not None and not crawl_task.done():
        await interaction.response.send_message(
            "A crawl is already running. "
            "Use /crawlstatus.",
            ephemeral=True,
        )
        return

    crawl_task = asyncio.create_task(
        run_crawl()
    )

    await interaction.response.send_message(
        "Season 2 crawl started.\n"
        "Use /crawlstatus to check progress.",
        ephemeral=True,
    )


# ---------------------------------------------------------
# /crawlstatus
# ---------------------------------------------------------

@bot.tree.command(
    name="crawlstatus",
    description="Check the Season 2 crawler status.",
)
@app_commands.guild_only()
@app_commands.check(has_allowed_role)
async def crawlstatus_command(
    interaction: discord.Interaction,
):
    if crawl_task is None:
        message = (
            "No crawl has been started "
            "since the bot launched."
        )

    elif not crawl_task.done():
        elapsed = (
            datetime.now() - crawl_started_at
        ).total_seconds() if crawl_started_at else 0

        message = (
            "**Crawl status: Running**\n"
            f"Elapsed time: {elapsed / 60:.1f} minutes"
        )

    elif crawl_error:
        message = (
            "**Crawl status: Failed**\n"
            "Check the bot console for error details."
        )

    else:
        finished = (
            crawl_finished_at.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if crawl_finished_at
            else "Unknown"
        )

        message = (
            "**Crawl status: Completed**\n"
            f"Finished: {finished}\n"
            "Rankings snapshot updated."
        )

    await interaction.response.send_message(
        message,
        ephemeral=True,
    )


# ---------------------------------------------------------
# Error handling
# ---------------------------------------------------------

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(
        error,
        app_commands.CommandOnCooldown,
    ):
        message = (
            "You're using this command too quickly. "
            f"Try again in "
            f"{error.retry_after:.1f} seconds."
        )

    elif isinstance(
        error,
        app_commands.CheckFailure,
    ):
        message = (
            "You don't have permission "
            "to use this command."
        )

    else:
        print(
            f"Unhandled slash-command error: {error!r}"
        )

        message = (
            "Something went wrong while processing "
            "that request. Please try again later."
        )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


# ---------------------------------------------------------
# Start bot
# ---------------------------------------------------------

if __name__ == "__main__":
    bot.run(TOKEN)
