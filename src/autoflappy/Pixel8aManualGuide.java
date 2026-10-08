package autoflappy;

import autoflappy.Pixel8aVision.Box;
import autoflappy.Pixel8aVision.Gap;
import autoflappy.Pixel8aVision.Observation;

/** Optional per-pillar point guidance from the dashboard overlay. */
public final class Pixel8aManualGuide {
    private Integer scooterX, pointX, pointY;
    private boolean manualMode, cleared;
    private Gap tracked;
    private long lastSeenNs;
    private double speedX;

    public synchronized void markScooter(int x) {
        scooterX = x;
    }

    public synchronized void markGap(int x, int y) {
        if (scooterX == null) throw new IllegalStateException("Mark the scooter first");
        pointX = x;
        pointY = y;
        manualMode = true;
        tracked = null;
        lastSeenNs = 0;
        speedX = 0;
        cleared = false;
    }

    public synchronized void clear() {
        scooterX = null;
        pointX = null;
        pointY = null;
        manualMode = false;
        tracked = null;
        lastSeenNs = 0;
        speedX = 0;
        cleared = false;
    }

    public synchronized boolean consumeCleared() {
        boolean result = cleared;
        cleared = false;
        return result;
    }

    public synchronized Observation guide(Observation raw, long nowNs, int w, int h) {
        Box scooter = raw.scooter;
        if (scooter != null && scooterX != null
                && Math.abs(scooter.centerX() - scooterX) > w * .08) scooter = null;
        if (pointX == null || pointY == null) {
            return new Observation(raw.gameplay, scooter, raw.gaps,
                    scooter != null && !manualMode ? raw.activeGap : null);
        }
        if (!raw.gameplay || scooter == null)
            return new Observation(raw.gameplay, scooter, raw.gaps, null);

        Gap best = null;
        double bestDistance = Double.MAX_VALUE;
        for (Gap candidate : raw.gaps) {
            boolean matches;
            double distance;
            if (tracked == null) {
                matches = candidate.top < pointY && pointY < candidate.bottom
                        && pointX >= candidate.left - w * .08
                        && pointX <= candidate.right + w * .08;
                distance = Math.abs((candidate.left + candidate.right) / 2.0 - pointX);
            } else {
                double dt = Math.max(0, (nowNs - lastSeenNs) / 1e9);
                double predictedLeft = tracked.left + speedX * dt;
                matches = Math.abs(candidate.left - predictedLeft) < w * .12
                        && Math.abs(candidate.top - tracked.top) < h * .04
                        && Math.abs(candidate.bottom - tracked.bottom) < h * .04;
                distance = Math.abs(candidate.left - predictedLeft);
            }
            if (matches && distance < bestDistance) {
                best = candidate;
                bestDistance = distance;
            }
        }
        if (best != null) {
            double dt = (nowNs - lastSeenNs) / 1e9;
            if (tracked != null && dt > .005 && dt < .15)
                speedX = Math.max(-w * 3, Math.min(0, (best.left - tracked.left) / dt));
            tracked = best;
            lastSeenNs = nowNs;
            if (best.right + Math.max(2, (int) (w * .01)) <= scooter.left) {
                pointX = null;
                pointY = null;
                tracked = null;
                cleared = true;
                best = null;
            }
        }
        return new Observation(raw.gameplay, scooter, raw.gaps, best);
    }
}
