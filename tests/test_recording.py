import csv

import pytest

from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.recording import (
    COUNTDOWN_S,
    GAZE_STEPS,
    GuidedRecording,
    NoSuchStep,
    PoseRecorder,
    RecordingError,
    Step,
)
from eyes_on_screen.vision.analyzer import EyeState, FaceObservation
from eyes_on_screen.vision.head_pose import HeadPose

FACE = FaceObservation(
    (0.4, 0.4, 0.42, 0.44),
    0.9,
    HeadPose(yaw=3.0, pitch=-5.0, roll=1.0),
    EyeState(look_down=0.6, look_up=0.0, closed=0.2, squint=0.3),
)
NO_LANDMARKS = FaceObservation((0.1, 0.1, 0.12, 0.14), 0.7, None)
STEPS = (
    Step("screen", "Watch the TV", "Watch it.", 2.0),
    Step("phone", "Phone", "Read it.", 1.0),
)
FPS = 10


def rows(path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def frames(recording: GuidedRecording, clock, seconds: float, face=FACE) -> None:
    """Feed `seconds` of frames the way the app does, ending finished steps."""
    for _ in range(round(seconds * FPS)):
        now = clock.advance(1 / FPS)
        recording.update(now)
        recording.add(now, [face] if face else [], face, Attention.LOOKING)


@pytest.fixture
def recording(tmp_path) -> GuidedRecording:
    return GuidedRecording(tmp_path / "rec" / "gaze.csv", STEPS)


def test_rows_are_recorded_after_the_countdown_and_labelled(recording, clock):
    recording.start(0, clock.now())

    frames(recording, clock, COUNTDOWN_S + 2.5)
    recording.close()

    written = rows(recording.path)
    assert len(written) == pytest.approx(2.0 * FPS, abs=1)
    first = written[0]
    assert (first["step"], first["take"], first["label"]) == ("1", "1", "screen")
    assert float(first["step_t"]) < 0.2
    assert (first["yaw"], first["pitch"], first["eye_down"], first["eye_squint"]) == (
        "3.0",
        "-5.0",
        "0.600",
        "0.300",
    )
    assert first["face_w"] == "0.0200"


def test_a_finished_step_reports_how_often_the_face_was_measured(recording, clock):
    recording.start(1, clock.now())
    frames(recording, clock, COUNTDOWN_S + 0.5)
    frames(recording, clock, 1.0, face=NO_LANDMARKS)

    [result] = recording.results
    assert (result.index, result.take) == (1, 1)
    assert result.frames == pytest.approx(1.0 * FPS, abs=1)
    assert result.with_face == pytest.approx(0.5 * FPS, abs=1)
    assert recording.last == 1
    assert recording.progress(clock.now()) is None


def test_progress_counts_down_then_records(recording, clock):
    recording.start(0, clock.now())

    counting = recording.progress(clock.advance(1.0))
    assert counting is not None
    assert (counting.phase, counting.remaining_s, counting.phase_s) == ("countdown", 4.0, 5.0)

    recording_now = recording.progress(clock.advance(COUNTDOWN_S - 1.0 + 0.5))
    assert recording_now is not None
    assert (recording_now.phase, recording_now.remaining_s) == ("recording", 1.5)


def test_one_step_at_a_time(recording, clock):
    recording.start(0, clock.now())

    with pytest.raises(RecordingError, match="step 1 is still running"):
        recording.start(1, clock.advance(1))
    with pytest.raises(NoSuchStep):
        recording.start(5, clock.now())


def test_a_redone_step_is_a_new_take(recording, clock):
    recording.start(1, clock.now())
    frames(recording, clock, COUNTDOWN_S + 1.5)
    recording.start(1, clock.now())
    frames(recording, clock, COUNTDOWN_S + 1.5)
    recording.close()

    assert {row["take"] for row in rows(recording.path)} == {"1", "2"}
    assert [r.take for r in recording.results] == [2]


def test_a_cancelled_step_stops_recording(recording, clock):
    recording.start(0, clock.now())
    frames(recording, clock, COUNTDOWN_S + 0.5)
    recording.cancel()
    frames(recording, clock, 1.0)
    recording.close()

    assert len(rows(recording.path)) == pytest.approx(0.5 * FPS, abs=1)
    assert recording.results == []


def test_no_file_until_the_first_step(recording):
    with pytest.raises(NoSuchStep):
        recording.start(-1, 0.0)
    recording.close()

    assert not recording.path.exists()


def test_pose_recorder_without_a_face(tmp_path):
    recorder = PoseRecorder(tmp_path / "poses.csv", started=10.0)

    recorder.write(10.5, [], None, Attention.ABSENT, "phone")
    recorder.close()

    [row] = rows(tmp_path / "poses.csv")
    assert (row["t"], row["label"], row["faces"], row["yaw"], row["attention"]) == (
        "0.50",
        "phone",
        "0",
        "",
        "absent",
    )


def test_the_gaze_script_covers_every_label_it_should_tell_apart():
    assert {step.label for step in GAZE_STEPS} == {"screen", "phone", "elsewhere", "closed"}
    assert all(step.duration_s >= 20 for step in GAZE_STEPS)
