import pytest

from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.attention.viewers import ViewerFilter, room_attention
from eyes_on_screen.config import MultipleViewers, PoseConfig
from eyes_on_screen.vision.analyzer import FaceObservation
from eyes_on_screen.vision.head_pose import HeadPose

POSE = PoseConfig(
    yaw_center_deg=0, pitch_center_deg=0, yaw_tolerance_deg=20, pitch_tolerance_deg=15
)
LOOK, TURNED, NO_LANDMARKS = HeadPose(0, 0, 0), HeadPose(45, 0, 0), None


def face(x: float, pose: HeadPose | None, size: float = 0.02) -> FaceObservation:
    return FaceObservation(box=(x, 0.4, x + size, 0.4 + 2 * size), score=0.9, pose=pose)


class TestViewerFilter:
    def test_faces_with_landmarks_are_viewers(self):
        viewer = face(0.3, LOOK)

        assert ViewerFilter().viewers([viewer], now=0) == [viewer]

    def test_face_that_never_had_landmarks_is_decor(self):
        pillow_cat = face(0.6, NO_LANDMARKS)

        assert ViewerFilter().viewers([pillow_cat], now=0) == []

    def test_viewer_who_turned_away_and_lost_landmarks_still_counts(self):
        filt = ViewerFilter()
        filt.viewers([face(0.30, LOOK)], now=0)
        turned = face(0.31, NO_LANDMARKS)

        assert filt.viewers([turned], now=5) == [turned]

    def test_the_vouching_expires(self):
        filt = ViewerFilter(memory_s=10)
        filt.viewers([face(0.30, LOOK)], now=0)

        assert filt.viewers([face(0.30, NO_LANDMARKS)], now=11) == []

    def test_a_viewer_elsewhere_does_not_vouch_for_the_pillow(self):
        filt = ViewerFilter()
        filt.viewers([face(0.30, LOOK)], now=0)
        pillow_cat = face(0.60, NO_LANDMARKS)

        assert filt.viewers([face(0.30, LOOK), pillow_cat], now=1) == [face(0.30, LOOK)]


class TestRoomAttention:
    def test_nobody_is_absent(self):
        result = room_attention([], POSE, MultipleViewers.ANY_AWAY)

        assert result.attention is Attention.ABSENT
        assert result.viewers == 0

    @pytest.mark.parametrize(
        ("mode", "poses", "expected"),
        [
            (MultipleViewers.ANY_AWAY, [LOOK, LOOK], Attention.LOOKING),
            (MultipleViewers.ANY_AWAY, [LOOK, TURNED], Attention.AWAY),
            (MultipleViewers.ANY_AWAY, [LOOK, NO_LANDMARKS], Attention.AWAY),
            (MultipleViewers.ALL_AWAY, [LOOK, TURNED], Attention.LOOKING),
            (MultipleViewers.ALL_AWAY, [TURNED, NO_LANDMARKS], Attention.AWAY),
        ],
    )
    def test_group_modes(self, mode, poses, expected):
        viewers = [face(0.1 + 0.2 * i, pose) for i, pose in enumerate(poses)]

        result = room_attention(viewers, POSE, mode)

        assert result.attention is expected
        assert result.looking == poses.count(LOOK)

    def test_nearest_follows_the_largest_face(self):
        near_and_looking = face(0.1, LOOK, size=0.05)
        far_and_turned = face(0.5, TURNED, size=0.02)

        result = room_attention([far_and_turned, near_and_looking], POSE, MultipleViewers.NEAREST)

        assert result.attention is Attention.LOOKING
