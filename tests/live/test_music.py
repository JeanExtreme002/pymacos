"""Tests of :mod:`macos.music` against the real system. Skipped outside macOS."""

import macos


def test_now_playing_never_opens_the_player():
    # By bundle identifier: the players' names are localized ("Musik" on a German Mac).
    players = {"com.apple.Music", "com.spotify.client"}
    running = {app.bundle_id for app in macos.apps.running()} & players

    track = macos.music.now_playing()

    assert track is None or track.app in macos.music.PLAYERS
    assert {app.bundle_id for app in macos.apps.running()} & players == running
