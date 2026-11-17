# Lore Seekers League
## About
The Lore Seekers League is a fan-made and fan-run Disney Lorcana League for Southern California players.

We support various counties of SoCal.

The League functions on the basis of tracking players' performances across various SoCal local events, as well as awarding Major Event bonuses to players for their best performances at such events.

A leaderboard is generated and updated periodically to provide players with up to date data on their standings and performance.

## Requirements
Python3 is required to execute the code base.

Beyond that, make sure to have required Python libraries installed.

## Discord
The Discord server for the League can be found [here!](discord.com/invite/dfN6mXBjgh)

# COMMON COMMANDS

Replace player name and event id to queue player and event (must have played in this event)
Add player AND events:

	python3 -c "from league_players import add_player_import_request; 	add_player_import_request('https://tcg.ravensburgerplay.com/events/605405', 'Rojellyb', '')" 

Commits all queued events and players from previous section:
	
    python3 admin_tools.py       


Aaccess db:

	sqlite3 lorcana_tracker.db  


Run tracker:

	python3 lorcana_tracker.py   


Must clear event data when new player is added to league players. Then re-run the tracker.