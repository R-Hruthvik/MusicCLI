"""Musicly Foundation CLI package."""

from .musiccli import (
    search_songs,
    search_playlists,
    get_playlist_tracks,
    get_radio_tracks,
    play_track,
    kill_process,
    Track,
)

__all__ = [
    "search_songs",
    "search_playlists",
    "get_playlist_tracks",
    "get_radio_tracks",
    "play_track",
    "kill_process",
    "Track",
]
