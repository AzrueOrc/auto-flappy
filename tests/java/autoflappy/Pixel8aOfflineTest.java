package autoflappy;

import autoflappy.Pixel8aVision.Box;
import autoflappy.Pixel8aVision.Gap;
import autoflappy.Pixel8aVision.Observation;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

/** Run with java -ea; no connected phone or test framework required. */
public final class Pixel8aOfflineTest {
    private static BufferedImage syntheticFrame(boolean rims) {
        BufferedImage frame = new BufferedImage(405, 900, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = frame.createGraphics();
        g.setColor(new Color(57, 167, 242)); g.fillRect(0, 0, 405, 900);
        g.setColor(Color.WHITE); g.fillRect(180, 65, 30, 20);
        g.setColor(new Color(18, 170, 79)); g.fillRect(90, 415, 48, 48);
        g.setColor(new Color(223, 175, 111));
        g.fillRect(252, 90, 68, 205);
        g.fillRect(252, 520, 68, 210);
        if (rims) {
            g.setColor(new Color(60, 43, 30));
            g.fillRect(248, 296, 76, 5);
            g.fillRect(248, 514, 76, 5);
            g.fillRect(250, 90, 3, 205);
            g.fillRect(319, 90, 3, 205);
            g.fillRect(250, 520, 3, 210);
            g.fillRect(319, 520, 3, 210);
        }
        g.dispose();
        return frame;
    }

    private static BufferedImage oversizedCandidate(int bodyWidth, int lowerStart) {
        BufferedImage frame = new BufferedImage(405, 900, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = frame.createGraphics();
        g.setColor(new Color(57, 167, 242)); g.fillRect(0, 0, 405, 900);
        g.setColor(Color.WHITE); g.fillRect(180, 65, 30, 20);
        g.setColor(new Color(18, 170, 79)); g.fillRect(90, 415, 48, 48);
        g.setColor(new Color(223, 175, 111));
        g.fillRect(180, 90, bodyWidth, 200);
        g.fillRect(180, lowerStart, bodyWidth, 750 - lowerStart);
        g.setColor(new Color(60, 43, 30));
        g.fillRect(176, 290, bodyWidth + 8, 5);
        g.fillRect(176, lowerStart - 6, bodyWidth + 8, 5);
        g.fillRect(178, 90, 3, 200);
        g.fillRect(180 + bodyWidth - 1, 90, 3, 200);
        g.fillRect(178, lowerStart, 3, 750 - lowerStart);
        g.fillRect(180 + bodyWidth - 1, lowerStart, 3, 750 - lowerStart);
        g.dispose();
        return frame;
    }

    private static void checkVision() {
        Pixel8aVision vision = new Pixel8aVision();
        Observation real = vision.analyze(syntheticFrame(true));
        assert real.gameplay : "synthetic gameplay scene";
        assert real.scooter != null : "scooter";
        assert real.activeGap != null : "paired brick pillars";
        assert real.activeGap.top < 320 && real.activeGap.bottom > 490 : "gap bounds";
        Observation background = vision.analyze(syntheticFrame(false));
        assert background.gaps.isEmpty() : "tan background without rims";
        assert vision.analyze(oversizedCandidate(68, 520)).activeGap != null
                : "ordinary pillar candidate";
        assert vision.analyze(oversizedCandidate(130, 520)).gaps.isEmpty()
                : "joined skyline width must not become a pillar";
        assert vision.analyze(oversizedCandidate(68, 650)).gaps.isEmpty()
                : "oversized vertical opening must not become a gap";
    }

    private static void checkOneTapPerRedEntry() {
        Pixel8aPlanner planner = new Pixel8aPlanner();
        for (int i = 0; i < 2; i++) {
            Gap gap = new Gap(186 - i * 3, 250 - i * 3, 300, 550);
            Observation frame = new Observation(true, new Box(82, 425, 137, 475),
                    java.util.Collections.singletonList(gap), gap);
            assert !planner.shouldTap(frame, 1_000_000_000L + i * 20_000_000L, 405, 900);
        }
        Gap gap = new Gap(180, 244, 300, 550);
        Observation red = new Observation(true, new Box(82, 425, 137, 475),
                java.util.Collections.singletonList(gap), gap);
        assert planner.shouldTap(red, 1_040_000_000L, 405, 900) : "first red entry";
        assert !planner.shouldTap(red, 1_300_000_000L, 405, 900) : "no repeated red tap";
        Observation green = new Observation(true, new Box(82, 400, 137, 450),
                java.util.Collections.singletonList(gap), gap);
        assert !planner.shouldTap(green, 1_320_000_000L, 405, 900);
        assert planner.shouldTap(red, 1_340_000_000L, 405, 900) : "green to red reentry";
    }

    private static void checkOpenSkyHold() {
        Pixel8aPlanner planner = new Pixel8aPlanner();
        Observation sky = new Observation(true, new Box(82, 410, 137, 470),
                java.util.Collections.emptyList(), null);
        assert !planner.shouldTap(sky, 1_000_000_000L, 405, 900);
        assert !planner.shouldTap(sky, 1_020_000_000L, 405, 900);
        assert planner.shouldTap(sky, 1_040_000_000L, 405, 900)
                : "hold altitude before the first pillar";
        assert !planner.shouldTap(sky, 1_100_000_000L, 405, 900)
                : "ADB tap cooldown";
        assert planner.shouldTap(sky, 1_160_000_000L, 405, 900)
                : "continue holding altitude while no pillar is visible";
    }

    private static void checkManualMarks() {
        Pixel8aManualGuide guide = new Pixel8aManualGuide();
        guide.markScooter(110);
        guide.markGap(210, 425);
        Box scooter = new Box(80, 400, 140, 470);
        for (int i = 0; i < 11; i++) {
            Gap gap = new Gap(180 - i * 20, 240 - i * 20, 300, 550);
            Observation raw = new Observation(true, scooter,
                    java.util.Collections.singletonList(gap), gap);
            Observation guided = guide.guide(raw, 1_000_000_000L + i * 20_000_000L, 405, 900);
            if (i == 0) assert guided.activeGap == gap : "manual point selects marked gap";
            if (i == 10) assert guided.activeGap == null : "mark ends after pillar clears";
        }
        assert guide.consumeCleared() : "dashboard receives next-gap signal";
        assert !guide.consumeCleared() : "next-gap signal is one shot";
    }

    public static void main(String[] args) throws Exception {
        checkVision();
        checkOneTapPerRedEntry();
        checkOpenSkyHold();
        checkManualMarks();
        Pixel8aVision vision = new Pixel8aVision();
        for (String filename : args) {
            File image = new File(filename);
            Observation observed = vision.analyze(ImageIO.read(image));
            if (image.getName().contains("resume")) {
                assert !observed.gameplay && observed.activeGap == null
                        : "resume screen must not trigger input";
            } else {
                assert observed.gameplay && observed.scooter != null
                        && observed.activeGap != null
                        : "active saved frame must keep the pillar target: " + filename;
            }
            if (image.getName().contains("skyline_interference"))
                assert observed.gaps.size() == 1 : "skyline must not become a gap";
            System.out.printf("%s gameplay=%s scooter=%s gaps=%d selected=%s%n",
                    image.getName(), observed.gameplay,
                    observed.scooter != null, observed.gaps.size(),
                    observed.activeGap != null);
            if (observed.scooter != null)
                System.out.printf("  scooter=(%d,%d)-(%d,%d)%n", observed.scooter.left,
                        observed.scooter.top, observed.scooter.right, observed.scooter.bottom);
            for (Gap opening : observed.gaps)
                System.out.printf("  gap=(%d,%d)-(%d,%d)%n", opening.left,
                        opening.top, opening.right, opening.bottom);
        }
        System.out.println("Pixel8aOfflineTest passed");
    }
}
