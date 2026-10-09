package autoflappy;

import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Pixel 8a version of the original Flappy and pipe scan-line detector. */
public final class Pixel8aVision {
    public static final class Box {
        public final int left, top, right, bottom;
        Box(int left, int top, int right, int bottom) {
            this.left = left; this.top = top; this.right = right; this.bottom = bottom;
        }
        public double centerX() { return (left + right) / 2.0; }
        public double centerY() { return (top + bottom) / 2.0; }
    }

    public static final class Gap {
        public final int left, right, top, bottom;
        Gap(int left, int right, int top, int bottom) {
            this.left = left; this.right = right; this.top = top; this.bottom = bottom;
        }
        public double centerY() { return (top + bottom) / 2.0; }
    }

    public static final class Observation {
        public final boolean gameplay;
        public final Box scooter;
        public final List<Gap> gaps;
        public final Gap activeGap;
        Observation(boolean gameplay, Box scooter, List<Gap> gaps, Gap activeGap) {
            this.gameplay = gameplay;
            this.scooter = scooter;
            this.gaps = gaps;
            this.activeGap = activeGap;
        }
    }

    private static final class Span {
        final int start, end;
        Span(int start, int end) { this.start = start; this.end = end; }
        int length() { return end - start; }
    }

    private static int red(int rgb) { return (rgb >>> 16) & 255; }
    private static int green(int rgb) { return (rgb >>> 8) & 255; }
    private static int blue(int rgb) { return rgb & 255; }

    private static boolean scooterGreen(int rgb) {
        int r = red(rgb), g = green(rgb), b = blue(rgb);
        return g > 75 && g < 240 && g > r * 1.3 && g > b * 1.15;
    }

    private static boolean brick(int rgb) {
        int r = red(rgb), g = green(rgb), b = blue(rgb);
        return (((r >= 190 && r <= 240 && g >= 140 && g <= 220 && b >= 60 && b <= 170)
                || (r > 240 && r <= 251 && g >= 175 && g <= 225 && b >= 105 && b <= 180))
                && r > g + 15 && r < g + 80 && g > b + 25);
    }

    private static boolean dark(int rgb) {
        return red(rgb) < 145 && green(rgb) < 110 && blue(rgb) < 90;
    }

    private static List<Span> runs(boolean[] values, int minimum) {
        List<Span> result = new ArrayList<>();
        int start = -1;
        for (int i = 0; i <= values.length; i++) {
            boolean on = i < values.length && values[i];
            if (on && start < 0) start = i;
            if (!on && start >= 0) {
                if (i - start >= minimum) result.add(new Span(start, i));
                start = -1;
            }
        }
        return result;
    }

    private static void fillShortGaps(boolean[] values, int maximum) {
        int start = -1;
        for (int i = 0; i <= values.length; i++) {
            boolean missing = i < values.length && !values[i];
            if (missing && start < 0) start = i;
            if (!missing && start >= 0) {
                if (start > 0 && i < values.length && i - start <= maximum)
                    Arrays.fill(values, start, i, true);
                start = -1;
            }
        }
    }

    private static Box findScooter(BufferedImage frame) {
        int w = frame.getWidth(), h = frame.getHeight();
        int x0 = (int) (w * .06), x1 = (int) (w * .34);
        int y0 = (int) (h * .15), y1 = (int) (h * .72);
        int rw = x1 - x0, rh = y1 - y0;
        int[][] integral = new int[rh + 1][rw + 1];
        for (int y = 0; y < rh; y++) {
            int row = 0;
            for (int x = 0; x < rw; x++) {
                if (scooterGreen(frame.getRGB(x0 + x, y0 + y))) row++;
                integral[y + 1][x + 1] = integral[y][x + 1] + row;
            }
        }
        int winW = Math.max(20, (int) (w * .14));
        int winH = Math.max(20, (int) (h * .09));
        int best = 0, bestX = 0, bestY = 0;
        for (int y = 0; y + winH <= rh; y += Math.max(3, h / 320)) {
            for (int x = 0; x + winW <= rw; x += Math.max(3, w / 160)) {
                int count = integral[y + winH][x + winW] - integral[y][x + winW]
                        - integral[y + winH][x] + integral[y][x];
                if (count > best) { best = count; bestX = x; bestY = y; }
            }
        }
        if (best < Math.max(45, (int) (w * h * .000025))) return null;
        int minX = winW, minY = winH, maxX = -1, maxY = -1;
        for (int y = 0; y < winH; y++) for (int x = 0; x < winW; x++) {
            if (scooterGreen(frame.getRGB(x0 + bestX + x, y0 + bestY + y))) {
                minX = Math.min(minX, x); maxX = Math.max(maxX, x);
                minY = Math.min(minY, y); maxY = Math.max(maxY, y);
            }
        }
        int padX = Math.max(4, (int) (w * .015));
        int padY = Math.max(4, (int) (h * .012));
        Box box = new Box(Math.max(0, x0 + bestX + minX - padX),
                Math.max(0, y0 + bestY + minY - padY),
                Math.min(x1, x0 + bestX + maxX + padX),
                Math.min(h, y0 + bestY + maxY + padY));
        return box.right - box.left < w * .09 || box.bottom - box.top < h * .04 ? null : box;
    }

    private static boolean hasRim(BufferedImage frame, int y, int left, int right,
                                  boolean requireTwoRows) {
        int w = frame.getWidth(), h = frame.getHeight();
        int x0 = Math.max(0, left - Math.max(3, (int) (w * .01)));
        int x1 = Math.min(w, right + Math.max(3, (int) (w * .01)));
        int radius = Math.max(6, (int) (h * .012));
        int needed = Math.max(8, (int) ((x1 - x0) * .62));
        int consecutive = 0;
        for (int yy = Math.max(0, y - radius); yy <= Math.min(h - 1, y + radius); yy++) {
            int run = 0, longest = 0;
            for (int x = x0; x < x1; x++) {
                run = dark(frame.getRGB(x, yy)) ? run + 1 : 0;
                longest = Math.max(longest, run);
            }
            consecutive = longest >= needed ? consecutive + 1 : 0;
            if (consecutive >= (requireTwoRows ? 2 : 1)) return true;
        }
        return false;
    }

    private static boolean hasSideBorder(BufferedImage frame, int side, Span upper,
                                         Span lower, int y0) {
        int w = frame.getWidth(), h = frame.getHeight();
        int inset = Math.max(3, (int) (h * .007));
        int ua = y0 + upper.start + inset, ub = y0 + upper.end - inset;
        int la = y0 + lower.start + inset, lb = y0 + lower.end - inset;
        if (ua >= ub || la >= lb) return false;
        int spread = Math.max(5, (int) (w * .025));
        for (int x = Math.max(0, side - spread); x < Math.min(w, side + spread + 1); x++) {
            int u = 0, l = 0;
            for (int y = ua; y < ub; y++) if (dark(frame.getRGB(x, y))) u++;
            for (int y = la; y < lb; y++) if (dark(frame.getRGB(x, y))) l++;
            if (u >= (ub - ua) * .55 && l >= (lb - la) * .55) return true;
        }
        return false;
    }

    private static List<Gap> findGaps(BufferedImage frame) {
        int w = frame.getWidth(), h = frame.getHeight();
        int y0 = (int) (h * .09), y1 = (int) (h * .82);
        boolean[] columns = new boolean[w];
        for (int x = 0; x < w; x++) {
            int count = 0;
            for (int y = y0; y < y1; y++) if (brick(frame.getRGB(x, y))) count++;
            columns[x] = count >= Math.max(50, (int) ((y1 - y0) * .17));
        }
        fillShortGaps(columns, Math.max(3, (int) (w * .04)));
        List<Gap> gaps = new ArrayList<>();
        int minimumBody = Math.max(35, (int) (h * .055));
        for (Span group : runs(columns, Math.max(15, (int) (w * .07)))) {
            int left = group.start, right = group.end;
            // Joined skyline buildings can make a very wide false "pillar".
            if (right - left > w * .25) continue;
            int innerLeft = left + (right - left) / 4;
            int innerRight = right - (right - left) / 4;
            boolean[] rows = new boolean[y1 - y0];
            for (int y = y0; y < y1; y++) {
                int count = 0;
                for (int x = innerLeft; x < innerRight; x++)
                    if (brick(frame.getRGB(x, y))) count++;
                rows[y - y0] = count >= (innerRight - innerLeft) * .48;
            }
            fillShortGaps(rows, Math.max(5, (int) (h * .012)));
            List<Span> raw = runs(rows, Math.max(14, (int) (h * .015)));
            List<Span> blocks = new ArrayList<>();
            for (int i = 0; i < raw.size(); i++) {
                Span block = raw.get(i);
                boolean nearbyBody = i + 1 < raw.size()
                        && raw.get(i + 1).length() >= minimumBody
                        && raw.get(i + 1).start - block.end <= h * .04;
                boolean shortCap = nearbyBody && hasRim(frame, y0 + block.start, left, right, false);
                boolean shortUpper = i == 0 && block.length() >= Math.max(20, (int) (h * .025))
                        && hasRim(frame, y0 + block.end, left, right, false);
                if (block.length() < minimumBody && !shortCap && !shortUpper) continue;
                if (!blocks.isEmpty()) {
                    Span previous = blocks.get(blocks.size() - 1);
                    if (block.start - previous.end <= h * .08
                            && Math.min(block.length(), previous.length()) < minimumBody) {
                        blocks.set(blocks.size() - 1, new Span(previous.start, block.end));
                        continue;
                    }
                }
                blocks.add(block);
            }
            boolean accepted = false;
            for (int i = 0; i < blocks.size() && !accepted; i++) {
                for (int j = i + 1; j < blocks.size(); j++) {
                    Span upper = blocks.get(i), lower = blocks.get(j);
                    int top = y0 + upper.end, bottom = y0 + lower.start;
                    if (bottom - top < h * .08 || bottom - top > h * .36) continue;
                    if (!hasRim(frame, top, left, right, true)
                            || !hasRim(frame, bottom, left, right, true)
                            || !hasSideBorder(frame, left, upper, lower, y0)
                            || (right < w - 2 && !hasSideBorder(frame, right, upper, lower, y0)))
                        continue;
                    gaps.add(new Gap(left, right, top, bottom));
                    accepted = true;
                    break;
                }
            }
        }
        return gaps;
    }

    private static boolean gameplay(BufferedImage frame) {
        int w = frame.getWidth(), h = frame.getHeight();
        int darkPanel = 0, panelPixels = 0, whiteScore = 0, scorePixels = 0;
        long middleSum = 0; int middlePixels = 0;
        for (int y = (int) (h * .20); y < h * .45; y++)
            for (int x = (int) (w * .25); x < w * .75; x++) {
                int rgb = frame.getRGB(x, y);
                middleSum += red(rgb) + green(rgb) + blue(rgb);
                middlePixels += 3;
            }
        for (int y = (int) (h * .28); y < h * .48; y++)
            for (int x = (int) (w * .18); x < w * .82; x++) {
                int rgb = frame.getRGB(x, y);
                if (Math.max(red(rgb), Math.max(green(rgb), blue(rgb))) < 95) darkPanel++;
                panelPixels++;
            }
        for (int y = (int) (h * .045); y < h * .19; y++)
            for (int x = (int) (w * .35); x < w * .68; x++) {
                int rgb = frame.getRGB(x, y);
                if (Math.min(red(rgb), Math.min(green(rgb), blue(rgb))) > 215) whiteScore++;
                scorePixels++;
            }
        return middlePixels > 0 && panelPixels > 0 && scorePixels > 0
                && middleSum / (double) middlePixels >= 100
                && darkPanel / (double) panelPixels <= .30
                && whiteScore / (double) scorePixels > .006;
    }

    public Observation analyze(BufferedImage frame) {
        boolean active = gameplay(frame);
        Box scooter = findScooter(frame);
        List<Gap> gaps = findGaps(frame);
        Gap selected = null;
        if (active && scooter != null) {
            int margin = Math.max(2, (int) (frame.getWidth() * .01));
            for (Gap gap : gaps) {
                if (gap.right + margin > scooter.left
                        && (selected == null || gap.right < selected.right)) selected = gap;
            }
        }
        return new Observation(active, scooter, gaps, selected);
    }
}
