package autoflappy;

import autoflappy.Pixel8aVision.Box;
import autoflappy.Pixel8aVision.Gap;
import autoflappy.Pixel8aVision.Observation;

/** The original height-targeting loop adapted to scooter and pillar geometry. */
public final class Pixel8aPlanner {
    private static final long MIN_TAP_NS = 110_000_000L;
    private Gap target;
    private int targetSeen;
    private int anchorX;
    private Gap lastVisibleGap;
    private int visibleCount;
    private long lastVisibleNs;
    private double gapVelocityX;
    private long lastFrameNs;
    private double lastY;
    private long lastTapNs = Long.MIN_VALUE;
    private int scooterFrames;
    private boolean clickZoneLatched;
    private Gap latchedGap;

    public void reset() {
        target = null;
        targetSeen = 0;
        lastVisibleGap = null;
        visibleCount = 0;
        lastVisibleNs = 0;
        gapVelocityX = 0;
        lastFrameNs = 0;
        scooterFrames = 0;
        clickZoneLatched = false;
        latchedGap = null;
        lastTapNs = Long.MIN_VALUE;
    }

    private static boolean sameGap(Gap a, Gap b, int w, int h) {
        return a != null && b != null && Math.abs(a.left - b.left) < w * .12
                && Math.abs(a.top - b.top) < h * .04
                && Math.abs(a.bottom - b.bottom) < h * .04;
    }

    private boolean tapReady(long nowNs) {
        return lastTapNs == Long.MIN_VALUE || nowNs - lastTapNs >= MIN_TAP_NS;
    }

    private Gap recoverGap(Gap visible, Box scooter, long nowNs, int w, int h) {
        if (visible != null) {
            if (lastVisibleGap != null && sameGap(lastVisibleGap, visible, w, h)) {
                visibleCount++;
                double dt = (nowNs - lastVisibleNs) / 1e9;
                if (dt > .005 && dt < .15)
                    gapVelocityX = Math.max(-w * 3, Math.min(0,
                            (visible.left - lastVisibleGap.left) / dt));
            } else {
                gapVelocityX = 0;
                visibleCount = 1;
            }
            lastVisibleGap = visible;
            lastVisibleNs = nowNs;
            return visible;
        }
        if (lastVisibleGap == null || visibleCount < 3
                || nowNs - lastVisibleNs > 200_000_000L)
            return null;
        int dx = (int) Math.round(gapVelocityX * ((nowNs - lastVisibleNs) / 1e9));
        Gap estimate = new Gap(lastVisibleGap.left + dx, lastVisibleGap.right + dx,
                lastVisibleGap.top, lastVisibleGap.bottom);
        return estimate.right + Math.max(2, (int) (w * .01)) > scooter.left
                ? estimate : null;
    }

    public boolean shouldTap(Observation observation, long nowNs, int w, int h) {
        if (!observation.gameplay || observation.scooter == null) {
            reset();
            return false;
        }
        Box scooter = observation.scooter;
        scooterFrames = Math.min(3, scooterFrames + 1);
        double speedY = 0;
        if (lastFrameNs != 0) {
            double dt = (nowNs - lastFrameNs) / 1e9;
            if (dt > .005 && dt < .12)
                speedY = Math.max(-h * 2, Math.min(h * 2,
                        (scooter.centerY() - lastY) / dt));
        }
        lastFrameNs = nowNs;
        lastY = scooter.centerY();

        Gap gap = recoverGap(observation.activeGap, scooter, nowNs, w, h);
        if (gap == null) {
            target = null;
            targetSeen = 0;
            if (lastVisibleGap != null && nowNs - lastVisibleNs < 250_000_000L)
                return false;
            if (scooterFrames >= 3
                    && tapReady(nowNs)
                    && scooter.centerY() + speedY * .12 > h * .43
                    && scooter.top >= h * .12 + Math.max(45, h * .08)
                    && speedY > -h * .18) {
                lastTapNs = nowNs;
                return true;
            }
            return false;
        }
        if (latchedGap != null && (gap.left > latchedGap.left + w * .10
                || Math.abs(gap.top - latchedGap.top) > h * .06
                || Math.abs(gap.bottom - latchedGap.bottom) > h * .06)) {
            clickZoneLatched = false;
            latchedGap = null;
        }
        boolean stable = sameGap(target, gap, w, h)
                && gap.left <= target.left + w * .015;
        targetSeen = stable ? Math.min(3, targetSeen + 1) : 1;
        if (!stable) anchorX = gap.left;
        target = gap;

        double span = gap.bottom - gap.top;
        double midpoint = (gap.top + gap.bottom) / 2.0;
        double inset = span * .15;
        double scooterHalf = (scooter.bottom - scooter.top) / 2.0;
        double clickStart = midpoint + span * .10;
        double clickEnd = gap.bottom - inset - scooterHalf;
        if (clickZoneLatched && scooter.centerY() < clickStart - Math.max(6, span * .04))
            clickZoneLatched = false;

        if (targetSeen < 3 || !tapReady(nowNs)
                || anchorX - gap.left < Math.max(2, (int) (w * .01))
                || gap.right + Math.max(2, (int) (w * .01)) <= scooter.left
                || span < h * .12 || clickStart >= clickEnd)
            return false;
        boolean nearPillar = gap.left - scooter.right <= w * .28;
        double upperFlapLimit = gap.top + inset + Math.max(45, h * .08) + scooterHalf;
        if (nearPillar && (upperFlapLimit >= clickEnd || scooter.centerY() < upperFlapLimit))
            return false;
        if (scooter.top < h * .12 + Math.max(45, h * .08)) return false;
        double projectedY = scooter.centerY() + speedY * .14;
        if (!clickZoneLatched && projectedY >= clickStart && speedY > -h * .18) {
            clickZoneLatched = true;
            latchedGap = gap;
            lastTapNs = nowNs;
            return true;
        }
        return false;
    }
}
