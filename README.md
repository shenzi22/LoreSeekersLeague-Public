# Lore Seekers League

## About

Lore Seekers League (LSL) is a fan-made and community-run Disney Lorcana league serving Southern California players.

The league tracks player performances at eligible local tournaments and selected major events. Players earn points based on tournament results, and rankings are updated periodically throughout each season.

This repository contains the Python-based tournament tracker, ranking system, and Discord bot used to manage the league.

## Features

- Tracks player results from Ravensburger Play Hub events.
- Maintains an SQLite database of players, stores, and tournament results.
- Calculates seasonal rankings using league-specific scoring rules.
- Supports approved local stores and major events.
- Generates player rankings and leaderboard exports.
- Provides Discord slash commands for rankings and league administration.

## Season 2 Configuration

Season 2 runs from October 16, 2026, through January 24, 2027.

The player opt-in deadline is December 6, 2026, at 11:59 PM Pacific.

The current long-season configuration includes:

| Setting | Value |
|---|---|
| Counted events | Best 10 |
| Maximum Set Championships | 4 |
| Maximum DTQs | 2 |
| Community point cap | 6 |
| Events per community point | 2 |

Season dates and scoring configuration can be found in `lorcana_tracker/constants.py`.

## Discord Bot

The Discord bot allows players to view rankings and authorized league administrators to manage tournament data.

| Command | Description | Access |
|---|---|---|
| `/rank` | View a player's ranking and point breakdown | Everyone |
| `/downloadrankings` | Download the latest rankings CSV | Admin |
| `/addplayer` | Add a league player using a Play Hub event | Admin |
| `/addstore` | Approve a store using a Play Hub event URL | Admin |
| `/crawl` | Update tournament results | Admin |
| `/crawlstatus` | Check the crawler's status | Admin |

Regular users are limited to one successful `/rank` lookup per week. Usage is recorded in SQLite and resets according to the Pacific-time calendar week.

## Requirements

- Python 3
- SQLite
- Python dependencies used by the tracker and Discord bot
- A Discord bot token if running the Discord integration

## Configuration

The bot reads its credentials and administrator role configuration from environment variables.

Copy `.env.example` to a new `.env` file and configure