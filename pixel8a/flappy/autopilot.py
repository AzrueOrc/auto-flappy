"""Conservative frame-by-frame flap decisions; this module never sends input."""
from __future__ import annotations

from dataclasses import dataclass

from .vision import Observation, PillarGap


GAP_CLEARANCE_FRACTION = .15
MIN_TAP_INTERVAL = .11
CLICK_ZONE_OFFSET_FRACTION = .10


@dataclass
class _Target:
    gap: PillarGap
    seen: int
    timestamp: float
    anchor_x: int


def clearance_bounds(gap: PillarGap) -> tuple[float, float]:
    """Inset each visible pillar edge by 15 percent of the opening height."""
    inset = (gap.bottom - gap.top) * GAP_CLEARANCE_FRACTION
    return gap.top + inset, gap.bottom - inset


def safe_height_band(gap: PillarGap, scooter_height: int,
                     frame_height: int) -> tuple[float, float]:
    """Scooter center range with room for its body and one upward flap."""
    top_limit, bottom_limit = clearance_bounds(gap)
    flap_rise = max(45, int(frame_height * .08))
    upper = top_limit + flap_rise + scooter_height / 2
    lower = bottom_limit - scooter_height / 2
    return upper, lower


def aim_height(gap: PillarGap) -> float:
    """The exact geometric midpoint of the visible opening."""
    return (gap.top + gap.bottom) / 2


def click_zone(gap: PillarGap, scooter_height: int) -> tuple[float, float]:
    """Lower corridor where a flap should start, with room above the lower rim."""
    top_limit, bottom_limit = clearance_bounds(gap)
    center = aim_height(gap)
    start = center + (gap.bottom - gap.top) * CLICK_ZONE_OFFSET_FRACTION
    end = bottom_limit - scooter_height / 2
    return max(top_limit + scooter_height / 2, start), end


def scan_lines(scooter_x: float, frame_width: int) -> tuple[int, int, int]:
    """Behind-pillar, scooter, and approaching-pillar columns."""
    bird = round(scooter_x)
    return (max(0, round(bird - frame_width * .16)), bird,
            min(frame_width - 1, round(bird + frame_width * .31)))


class FlapPlanner:
    def __init__(self) -> None:
        self._target: _Target | None = None
        self._last_y: float | None = None
        self._last_frame_time: float | None = None
        self._last_tap = float("-inf")
        self._scooter_frames = 0
        self._last_gap_time = float("-inf")
        self._click_zone_latched = False
        self._latched_gap: PillarGap | None = None

    def reset(self) -> None:
        self._target = None
        self._last_y = None
        self._last_frame_time = None
        self._last_tap = float("-inf")
        self._scooter_frames = 0
        self._last_gap_time = float("-inf")
        self._click_zone_latched = False
        self._latched_gap = None

    def observe(self, observation: Observation, frame_time: float, now: float,
                width: int, height: int) -> bool:
        if (now - frame_time > .15 or observation.scene != "GAMEPLAY_CANDIDATE"
                or observation.scooter is None):
            self._target = None
            self._last_y = None
            self._last_frame_time = None
            self._scooter_frames = 0
            return False

        gap = observation.active_gap
        scooter = observation.scooter
        self._scooter_frames = min(3, self._scooter_frames + 1)

        speed_y = 0.0
        if self._last_y is not None and self._last_frame_time is not None:
            dt = frame_time - self._last_frame_time
            if .005 < dt < .12:
                speed_y = max(-height * 2, min(height * 2,
                                              (scooter.center_y - self._last_y) / dt))
        self._last_y = scooter.center_y
        self._last_frame_time = frame_time

        if gap is None:
            self._target = None
            # A missing detection near a recently seen pillar may be an
            # occlusion. Wait briefly before using the open-sky height hold.
            if (self._scooter_frames < 3 or now - self._last_gap_time < .25
                    or now - self._last_tap < MIN_TAP_INTERVAL):
                return False
            projected_y = scooter.center_y + speed_y * .12
            ceiling = height * .12 + max(45, int(height * .08))
            if (projected_y > height * .43 and scooter.top >= ceiling
                    and speed_y > -height * .18):
                self._last_tap = now
                return True
            return False

        self._last_gap_time = now
        latched_gap = self._latched_gap
        if (latched_gap is not None
                and (gap.left > latched_gap.left + width * .10
                     or abs(gap.top - latched_gap.top) > height * .06
                     or abs(gap.bottom - latched_gap.bottom) > height * .06)):
            # A different pillar has become the selected target.
            self._click_zone_latched = False
            self._latched_gap = None
        previous = self._target
        stable = (previous is not None
                  and abs(previous.gap.left - gap.left) < width * .09
                  and abs(previous.gap.right - gap.right) < width * .09
                  and abs(previous.gap.top - gap.top) < height * .025
                  and abs(previous.gap.bottom - gap.bottom) < height * .025
                  and gap.left <= previous.gap.left + width * .015
                  and frame_time > previous.timestamp)
        self._target = _Target(gap, min(3, previous.seen + 1) if stable else 1,
                               frame_time, previous.anchor_x if stable else gap.left)

        click_start, click_end = click_zone(gap, scooter.bottom - scooter.top)
        if (self._click_zone_latched and click_start < click_end
                and scooter.center_y < click_start - max(6, (gap.bottom - gap.top) * .04)):
            self._click_zone_latched = False

        if self._target.seen < 3 or now - self._last_tap < MIN_TAP_INTERVAL:
            return False
        if self._target.anchor_x - gap.left < max(2, int(width * .01)):
            return False
        # Continue height control until the scooter has fully left the pillar.
        if gap.right + max(2, int(width * .01)) <= scooter.left:
            return False
        if gap.bottom - gap.top < height * .12:
            return False

        upper, lower = safe_height_band(gap, scooter.bottom - scooter.top, height)
        near_pillar = gap.left - scooter.right <= width * .28
        if near_pillar and (upper >= lower or scooter.center_y < upper):
            return False
        if scooter.top < height * .12 + max(45, int(height * .08)):
            return False

        # The scooter coasts in the upper no-click area and flaps after it
        # approaches the lower click area. The geometric aim remains center.
        if click_start >= click_end:
            return False
        projected_y = scooter.center_y + speed_y * .14
        if (not self._click_zone_latched and projected_y >= click_start
                and speed_y > -height * .18):
            self._last_tap = now
            self._click_zone_latched = True
            self._latched_gap = gap
            return True
        return False
