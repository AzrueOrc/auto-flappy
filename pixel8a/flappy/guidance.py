"""Optional user-marked scooter lane and per-pillar gap selection."""
from __future__ import annotations

from dataclasses import replace

from .vision import Observation, PillarGap


class ManualGuidance:
    def __init__(self) -> None:
        self.scooter_x: int | None = None
        self.gap_point: tuple[int, int] | None = None
        self.manual_mode = False
        self._tracked: PillarGap | None = None
        self._seen = 0
        self._last_time = 0.0
        self._speed_x = 0.0

    def mark_scooter(self, x: int) -> None:
        self.scooter_x = x

    def mark_gap(self, x: int, y: int) -> None:
        if self.scooter_x is None:
            raise ValueError("Mark the scooter first")
        self.gap_point = (x, y)
        self.manual_mode = True
        self._tracked = None
        self._seen = 0
        self._speed_x = 0.0

    def clear(self) -> None:
        self.__init__()

    def guide(self, observation: Observation, timestamp: float,
              width: int, height: int) -> Observation:
        scooter = observation.scooter
        if (scooter is not None and self.scooter_x is not None
                and abs(scooter.center_x - self.scooter_x) > width * .08):
            scooter = None
        if self.gap_point is None:
            return replace(observation, scooter=scooter,
                           active_gap=(observation.active_gap if scooter and not self.manual_mode
                                       else None))
        if observation.scene != "GAMEPLAY_CANDIDATE" or scooter is None:
            return replace(observation, scooter=scooter, active_gap=None)

        point_x, point_y = self.gap_point
        gap = None
        if self._tracked is None:
            choices = [candidate for candidate in observation.gaps
                       if candidate.top < point_y < candidate.bottom
                       and candidate.left - width * .08 <= point_x <= candidate.right + width * .08]
            if choices:
                gap = min(choices, key=lambda candidate:
                          abs((candidate.left + candidate.right) / 2 - point_x))
        else:
            elapsed = timestamp - self._last_time
            predicted_left = self._tracked.left + self._speed_x * max(0, elapsed)
            choices = [candidate for candidate in observation.gaps
                       if abs(candidate.left - predicted_left) < width * .12
                       and abs(candidate.top - self._tracked.top) < height * .04
                       and abs(candidate.bottom - self._tracked.bottom) < height * .04]
            if choices:
                gap = min(choices, key=lambda candidate: abs(candidate.left - predicted_left))

        if gap is not None:
            if self._tracked is not None and .005 < timestamp - self._last_time < .15:
                dx = gap.left - self._tracked.left
                self._speed_x = max(-width * 3, min(0, dx / (timestamp - self._last_time)))
            self._tracked = gap
            self._last_time = timestamp
            self._seen += 1
        if gap is not None and gap.right + max(2, int(width * .01)) <= scooter.left:
            self.gap_point = None
            self._tracked = None
            gap = None
        return replace(observation, scooter=scooter, active_gap=gap)


class GapContinuity:
    """Bridge a short loss of an already validated moving pillar."""
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._gap: PillarGap | None = None
        self._seen = 0
        self._last_time = 0.0
        self._speed_x = 0.0
        self.estimated = False

    def guide(self, observation: Observation, timestamp: float,
              width: int) -> Observation:
        self.estimated = False
        scooter = observation.scooter
        if observation.scene != "GAMEPLAY_CANDIDATE" or scooter is None:
            self.reset()
            return observation
        gap = observation.active_gap
        if gap is not None:
            old = self._gap
            dt = timestamp - self._last_time
            same = (old is not None and .005 < dt < .15
                    and abs(gap.left - old.left) < width * .12
                    and abs(gap.top - old.top) < 30
                    and abs(gap.bottom - old.bottom) < 30)
            if same:
                self._speed_x = max(-width * 3, min(0, (gap.left - old.left) / dt))
                self._seen += 1
            else:
                self._speed_x = 0.0
                self._seen = 1
            self._gap = gap
            self._last_time = timestamp
            return observation
        if self._gap is None or self._seen < 3:
            return observation
        elapsed = timestamp - self._last_time
        if not 0 <= elapsed <= .20:
            self.reset()
            return observation
        old = self._gap
        dx = round(self._speed_x * elapsed)
        inferred = PillarGap(old.left + dx, old.right + dx, old.top, old.bottom)
        if inferred.right + max(2, int(width * .01)) <= scooter.left:
            self.reset()
            return observation
        self.estimated = True
        return replace(observation, active_gap=inferred)
