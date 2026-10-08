"""Conservative color geometry for the supplied Pixel 8a game screenshot.

This detector produces observations only. It never sends input. Thresholds are
reference values and need validation on unobstructed gameplay frames.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class PillarGap:
    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class Observation:
    scene: str
    scooter: Box | None
    gaps: tuple[PillarGap, ...]
    active_gap: PillarGap | None


def select_active_gap(gaps: tuple[PillarGap, ...], scooter: Box,
                      frame_width: int) -> PillarGap | None:
    """Use the nearest pillar until the scooter's trailing edge clears it."""
    margin = max(2, int(frame_width * .01))
    unfinished = [gap for gap in gaps if gap.right + margin > scooter.left]
    return min(unfinished, key=lambda gap: gap.right) if unfinished else None


def _runs(values: np.ndarray, minimum: int) -> list[tuple[int, int]]:
    edges = np.diff(np.r_[False, values.astype(bool), False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a >= minimum]


def _fill_short_gaps(values: np.ndarray, maximum: int) -> np.ndarray:
    result = values.copy()
    for a, b in _runs(~values, 1):
        if a > 0 and b < len(values) and b - a <= maximum:
            result[a:b] = True
    return result


def _scooter(rgb: np.ndarray) -> Box | None:
    h, w, _ = rgb.shape
    x0, x1 = int(w * .06), int(w * .34)
    y0, y1 = int(h * .15), int(h * .72)
    roi = rgb[y0:y1, x0:x1].astype(np.int16)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    green = (g > 75) & (g < 240) & (g > r * 1.3) & (g > b * 1.15)
    if not green.any():
        return None
    # Pick the densest scooter-sized patch. The limited X range excludes most
    # of the score text and the lower Y limit excludes the green Bolt sign.
    win_w, win_h = max(20, int(w * .14)), max(20, int(h * .09))
    integral = np.pad(green.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    best = (0, 0, 0)
    for yy in range(0, max(1, green.shape[0] - win_h), max(3, h // 320)):
        xx = np.arange(0, max(1, green.shape[1] - win_w), max(3, w // 160))
        if xx.size == 0:
            continue
        yy2 = min(yy + win_h, green.shape[0])
        xx2 = np.minimum(xx + win_w, green.shape[1])
        counts = integral[yy2, xx2] - integral[yy, xx2] - integral[yy2, xx] + integral[yy, xx]
        index = int(np.argmax(counts))
        if counts[index] > best[0]:
            best = (int(counts[index]), int(xx[index]), yy)
    count, xx, yy = best
    if count < max(45, int(w * h * .000025)):
        return None
    patch = green[yy:yy + win_h, xx:xx + win_w]
    ys, xs = np.where(patch)
    if len(xs) == 0:
        return None
    # Pad for the rider and dark scooter outline, which are not green pixels.
    pad_x, pad_y = max(4, int(w * .015)), max(4, int(h * .012))
    box = Box(max(0, x0 + xx + int(xs.min()) - pad_x),
              max(0, y0 + yy + int(ys.min()) - pad_y),
              min(x1, x0 + xx + int(xs.max()) + pad_x),
              min(h, y0 + yy + int(ys.max()) + pad_y))
    if box.right - box.left < w * .09 or box.bottom - box.top < h * .04:
        return None
    return box


def _pillars(rgb: np.ndarray) -> tuple[PillarGap, ...]:
    h, w, _ = rgb.shape
    y0, y1 = int(h * .09), int(h * .82)
    section = rgb[y0:y1].astype(np.int16)
    r, g, b = section[:, :, 0], section[:, :, 1], section[:, :, 2]
    main_brick = ((r >= 190) & (r <= 240) & (g >= 140) & (g <= 220)
                  & (b >= 60) & (b <= 170) & (r > g + 15)
                  & (r < g + 80) & (g > b + 25))
    light_brick = ((r > 240) & (r <= 251) & (g >= 175) & (g <= 225)
                   & (b >= 105) & (b <= 180) & (r > g + 15)
                   & (r < g + 75) & (g > b + 25))
    tan = main_brick | light_brick
    # The sky and skyline can contain pillar-like tan pixels. Real openings
    # have a dark, nearly full-width rim on both facing ends of the pillars.
    dark = (rgb[:, :, 0] < 145) & (rgb[:, :, 1] < 110) & (rgb[:, :, 2] < 90)
    occupancy = tan.sum(axis=0)
    columns = occupancy >= max(50, int((y1 - y0) * .17))
    columns = _fill_short_gaps(columns, max(3, int(w * .04)))
    groups = _runs(columns, max(15, int(w * .07)))
    gaps: list[PillarGap] = []
    for left, right in groups:
        inner_left = left + (right - left) // 4
        inner_right = right - (right - left) // 4
        rows = tan[:, inner_left:inner_right].mean(axis=1) >= .48
        rows = _fill_short_gaps(rows, max(5, int(h * .012)))
        minimum_body = max(35, int(h * .055))
        # A short span can be the wide cap of a cropped pillar. Keep it only
        # when a tall body follows very closely; isolated skyline patches
        # otherwise shift the apparent edge of the opening.
        raw_all = _runs(rows, max(14, int(h * .015)))
        raw_blocks = []
        for index, (a, b) in enumerate(raw_all):
            nearby_body = (index + 1 < len(raw_all)
                           and raw_all[index + 1][1] - raw_all[index + 1][0] >= minimum_body
                           and raw_all[index + 1][0] - b <= int(h * .04))
            def has_short_rim(edge: int) -> bool:
                cap_y = y0 + edge
                cap_left = max(0, left - max(3, int(w * .01)))
                cap_right = min(w, right + max(3, int(w * .01)))
                radius = max(6, int(h * .012))
                strip = dark[max(0, cap_y - radius):min(h, cap_y + radius + 1),
                             cap_left:cap_right]
                minimum_rim = max(8, int(strip.shape[1] * .62))
                return bool(strip.size and any(_runs(row, minimum_rim)
                                               for row in strip))

            short_cap = nearby_body and has_short_rim(a)
            short_upper = (index == 0 and b - a >= max(20, int(h * .025))
                           and has_short_rim(b))
            if b - a >= minimum_body or short_cap or short_upper:
                raw_blocks.append((a, b))
        blocks: list[tuple[int, int]] = []
        for a, b in raw_blocks:
            if (blocks and a - blocks[-1][1] <= int(h * .08)
                    and min(b - a, blocks[-1][1] - blocks[-1][0]) < minimum_body):
                blocks[-1] = (blocks[-1][0], b)
            else:
                blocks.append((a, b))
        if len(blocks) < 2:
            continue
        # A pair consists of two tall pillar spans separated by free space.
        for upper, lower in combinations(blocks, 2):
            gap_top, gap_bottom = y0 + upper[1], y0 + lower[0]
            if gap_bottom - gap_top >= int(h * .08):
                cap_left = max(0, left - max(3, int(w * .01)))
                cap_right = min(w, right + max(3, int(w * .01)))
                radius = max(6, int(h * .012))
                def has_rim(y: int) -> bool:
                    strip = dark[max(0, y - radius):min(h, y + radius + 1),
                                 cap_left:cap_right]
                    if not strip.size:
                        return False
                    minimum = max(8, int(strip.shape[1] * .62))
                    rim_rows = np.array([bool(_runs(row, minimum)) for row in strip])
                    return bool(_runs(rim_rows, 2))

                def has_side_border(side: int) -> bool:
                    # Match the same vertical outline above and below the gap.
                    # A clipped pillar needs only its visible side checked.
                    inset = max(3, int(h * .007))
                    upper_rows = dark[y0 + upper[0] + inset:y0 + upper[1] - inset]
                    lower_rows = dark[y0 + lower[0] + inset:y0 + lower[1] - inset]
                    if not upper_rows.size or not lower_rows.size:
                        return False
                    spread = max(5, int(w * .025))
                    for x in range(max(0, side - spread), min(w, side + spread + 1)):
                        if (upper_rows[:, x].mean() >= .55
                                and lower_rows[:, x].mean() >= .55):
                            return True
                    return False

                visible_sides = [left]
                if right < w - 2:
                    visible_sides.append(right)
                if (has_rim(gap_top) and has_rim(gap_bottom)
                        and all(has_side_border(side) for side in visible_sides)):
                    gaps.append(PillarGap(left, right, gap_top, gap_bottom))
                    break
    return tuple(gaps)


def analyze(rgb: np.ndarray) -> Observation:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("Expected an HxWx3 uint8 RGB frame")
    h, w, _ = rgb.shape
    middle = rgb[int(h * .20):int(h * .45), int(w * .25):int(w * .75)]
    panel = rgb[int(h * .28):int(h * .48), int(w * .18):int(w * .82)]
    score_zone = rgb[int(h * .045):int(h * .19), int(w * .35):int(w * .68)]
    if not middle.size or not panel.size or not score_zone.size:
        return Observation("UNKNOWN", None, (), None)
    # Results screens cover the playfield with a dark panel and may show green
    # buttons. Reject them before looking for scooter-colored pixels.
    dark_panel_fraction = float((panel.max(axis=2) < 95).mean())
    if float(middle.mean()) < 100 or dark_panel_fraction > .30:
        return Observation("MENU_OR_UNKNOWN", None, (), None)
    score_white_fraction = float((score_zone.min(axis=2) > 215).mean())
    scene = "GAMEPLAY_CANDIDATE" if score_white_fraction > .006 else "PAUSED_OR_START"
    scooter = _scooter(rgb)
    gaps = _pillars(rgb)
    active = None
    if scooter and scene == "GAMEPLAY_CANDIDATE":
        # Keep controlling a pillar while any part of the scooter overlaps it.
        # Switching when its center passes the right edge can stop taps before
        # the scooter's trailing side has exited the opening.
        active = select_active_gap(gaps, scooter, w)
    return Observation(scene, scooter, gaps, active)
