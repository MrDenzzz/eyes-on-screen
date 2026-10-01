import pytest

from eyes_on_screen.appletv.state import Playback, PlayerState
from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.attention.state_machine import Decision, PlaybackCommand, PlaybackStateMachine
from eyes_on_screen.config import BehaviorConfig, FaceLostAction

LOOKING, AWAY, ABSENT = Attention.LOOKING, Attention.AWAY, Attention.ABSENT
PLAYING = PlayerState(Playback.PLAYING, app="TV", title="Show")
PAUSED = PlayerState(Playback.PAUSED, app="TV", title="Show")
BEHAVIOR = BehaviorConfig(
    pause_after_s=1.5, resume_after_s=0.5, on_face_lost=FaceLostAction.PAUSE, face_lost_after_s=3.0
)
FPS = 10


class Room:
    """Drives the machine like the app does: one observation per analysed frame."""

    def __init__(self, clock, behavior: BehaviorConfig = BEHAVIOR, player=PLAYING) -> None:
        self.clock = clock
        self.machine = PlaybackStateMachine(behavior)
        self.player(player)

    def watch(self, attention: Attention, seconds: float) -> list[Decision]:
        """`seconds` worth of frames; the first one arrives one frame period from now."""
        decisions = []
        for _ in range(round(seconds * FPS)):
            decision = self.machine.observe(attention, self.clock.advance(1 / FPS))
            if decision is not None:
                decisions.append(decision)
        return decisions

    def player(self, state: PlayerState | None) -> None:
        self.machine.player_changed(state, self.clock.now())

    def pause_and_confirm(self) -> None:
        self.watch(LOOKING, 1)
        [decision] = self.watch(AWAY, 1.7)
        assert decision.command is PlaybackCommand.PAUSE
        self.player(PAUSED)


@pytest.fixture
def room(clock) -> Room:
    return Room(clock)


def commands(decisions: list[Decision]) -> list[PlaybackCommand]:
    return [d.command for d in decisions]


class TestPause:
    def test_pauses_once_the_viewer_looked_away_long_enough(self, room):
        room.watch(LOOKING, 1)

        assert room.watch(AWAY, 1.5) == []  # the 15th frame is 1.4 s after the first
        [decision] = room.watch(AWAY, 0.2)

        assert decision.command is PlaybackCommand.PAUSE
        assert "looked away" in decision.reason

    def test_short_glances_away_restart_the_timer(self, room):
        for _ in range(3):
            assert room.watch(AWAY, 1.2) == []
            assert room.watch(LOOKING, 0.1) == []

    def test_viewer_leaving_pauses_after_the_face_lost_delay(self, room):
        assert room.watch(ABSENT, 3.0) == []
        [decision] = room.watch(ABSENT, 0.2)

        assert decision.command is PlaybackCommand.PAUSE
        assert "no viewer" in decision.reason

    def test_viewer_leaving_can_be_ignored(self, clock):
        room = Room(clock, BEHAVIOR.model_copy(update={"on_face_lost": FaceLostAction.IGNORE}))

        assert room.watch(ABSENT, 30) == []

    @pytest.mark.parametrize("playback", [Playback.IDLE, Playback.STOPPED, Playback.LOADING])
    def test_nothing_to_pause_when_not_playing(self, clock, playback):
        room = Room(clock, player=PlayerState(playback))

        assert room.watch(AWAY, 10) == []

    def test_no_commands_while_the_apple_tv_is_disconnected(self, room):
        room.player(None)

        assert room.watch(AWAY, 10) == []

    def test_a_gap_in_the_video_restarts_the_timer(self, room):
        room.watch(AWAY, 1.0)
        room.clock.advance(10)  # stream stalled: no observations at all

        assert room.watch(AWAY, 1.0) == []
        assert commands(room.watch(AWAY, 0.7)) == [PlaybackCommand.PAUSE]


class TestResume:
    def test_resumes_our_own_pause_once_the_viewer_looks_back(self, room):
        room.pause_and_confirm()

        assert room.watch(LOOKING, 0.5) == []
        [decision] = room.watch(LOOKING, 0.2)

        assert decision.command is PlaybackCommand.RESUME
        assert "looking at the screen" in decision.reason

    def test_never_resumes_a_pause_from_the_remote(self, room):
        room.watch(LOOKING, 1)
        room.player(PAUSED)  # no pause was sent: someone pressed the remote

        assert room.watch(LOOKING, 30) == []

    def test_does_not_resume_while_the_viewer_still_looks_away(self, room):
        room.pause_and_confirm()

        assert room.watch(AWAY, 30) == []

    def test_reconnecting_keeps_ownership_of_our_pause(self, room):
        room.pause_and_confirm()
        room.player(None)
        room.player(PAUSED)

        assert commands(room.watch(LOOKING, 0.7)) == [PlaybackCommand.RESUME]

    def test_our_pause_is_forgotten_when_playback_stops(self, room):
        room.pause_and_confirm()
        room.player(PlayerState(Playback.IDLE))
        room.player(PAUSED)  # e.g. something else was started and paused later

        assert room.watch(LOOKING, 5) == []


class TestManualPlayback:
    def test_after_a_manual_play_we_wait_for_a_viewer_to_look(self, room):
        room.pause_and_confirm()
        room.player(PLAYING)  # resumed from the remote while still looking away

        assert room.watch(AWAY, 10) == []  # e.g. listening from the kitchen
        room.watch(LOOKING, 0.1)
        assert commands(room.watch(AWAY, 1.7)) == [PlaybackCommand.PAUSE]

    def test_next_episode_autoplay_keeps_watching(self, room):
        room.watch(LOOKING, 1)
        room.player(PlayerState(Playback.LOADING))
        room.player(PlayerState(Playback.PLAYING, app="TV", title="Next episode"))

        assert commands(room.watch(AWAY, 1.7)) == [PlaybackCommand.PAUSE]


class TestCommandConfirmation:
    def test_an_unconfirmed_command_is_resent_after_the_timeout(self, room):
        room.watch(LOOKING, 1)
        assert commands(room.watch(AWAY, 1.7)) == [PlaybackCommand.PAUSE]

        assert room.watch(AWAY, 2.7) == []  # waiting for the Apple TV to confirm
        assert commands(room.watch(AWAY, 0.5)) == [PlaybackCommand.PAUSE]  # 3 s passed: resent

    def test_no_duplicate_while_a_command_is_in_flight(self, room):
        room.watch(LOOKING, 1)

        assert commands(room.watch(AWAY, 4.0)) == [PlaybackCommand.PAUSE]


def test_status_snapshot(room):
    room.pause_and_confirm()

    status = room.machine.status(room.clock.now())

    assert status.attention is AWAY
    assert status.playback is Playback.PAUSED
    assert status.paused_by_us
    assert status.pending is None
    assert status.streak_s == pytest.approx(1.6)
