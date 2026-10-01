"""From all faces in the ROI to one attention value for the room."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.config import MultipleViewers, PoseConfig
from eyes_on_screen.vision.analyzer import FaceObservation
from eyes_on_screen.vision.target import select_target

# How long a confirmed face vouches for an unconfirmed one at the same spot.
CONFIRMED_MEMORY_S = 10.0
# "Same spot": centres closer than this many face widths / heights.
_SAME_SPOT = 1.5


@dataclass(frozen=True, slots=True)
class RoomAttention:
    attention: Attention
    viewers: int
    looking: int


class ViewerFilter:
    """Tells viewers from face-like decor.

    A face with landmarks is a viewer. A face without them is one only if a confirmed
    face was seen at the same spot within CONFIRMED_MEMORY_S: a viewer who turned far
    enough away to lose landmarks. A face that never had landmarks there is decor, like
    the cats printed on the sofa pillow, and must not keep the room "occupied".
    """

    def __init__(self, memory_s: float = CONFIRMED_MEMORY_S) -> None:
        self._memory_s = memory_s
        self._confirmed: list[tuple[float, FaceObservation]] = []

    def viewers(self, faces: Sequence[FaceObservation], now: float) -> list[FaceObservation]:
        self._confirmed = [(t, f) for t, f in self._confirmed if now - t <= self._memory_s]
        confirmed = [face for face in faces if face.pose is not None]
        self._confirmed.extend((now, face) for face in confirmed)
        turned_away = [face for face in faces if face.pose is None and self._seen_here(face)]
        return confirmed + turned_away

    def _seen_here(self, face: FaceObservation) -> bool:
        x, y = face.center
        width = face.box[2] - face.box[0]
        height = face.box[3] - face.box[1]
        for _, seen in self._confirmed:
            sx, sy = seen.center
            if abs(x - sx) <= _SAME_SPOT * width and abs(y - sy) <= _SAME_SPOT * height:
                return True
        return False


def room_attention(
    viewers: Sequence[FaceObservation], pose: PoseConfig, mode: MultipleViewers
) -> RoomAttention:
    if not viewers:
        return RoomAttention(Attention.ABSENT, viewers=0, looking=0)
    states = [classify(viewer, pose) for viewer in viewers]
    looking = states.count(Attention.LOOKING)

    if mode is MultipleViewers.NEAREST:
        attention = classify(select_target(viewers), pose)
    elif mode is MultipleViewers.ANY_AWAY:
        attention = Attention.LOOKING if looking == len(states) else Attention.AWAY
    else:
        attention = Attention.LOOKING if looking else Attention.AWAY
    return RoomAttention(attention, viewers=len(viewers), looking=looking)
