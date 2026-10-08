package autoflappy;

import java.awt.AWTException;
import java.awt.GraphicsDevice;
import java.awt.GraphicsEnvironment;
import java.awt.Rectangle;
import java.awt.Robot;
import java.awt.image.BufferedImage;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.imageio.ImageIO;

/** Runs the original scan-and-flap idea against a scrcpy Pixel 8a mirror. */
public final class Pixel8aAutoFlappy {
    private final Properties settings = new Properties();
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final Pixel8aVision vision = new Pixel8aVision();
    private final Pixel8aPlanner planner = new Pixel8aPlanner();
    private Robot robot;
    private Rectangle mirror;
    private final String mirrorTitle;
    private final String adbPath;
    private final String serial;
    private final int touchX, touchY;
    private Thread worker;
    private volatile String status = "Idle";
    private volatile long frames, taps, lastTapMs;

    public Pixel8aAutoFlappy(String configPath) throws IOException, AWTException {
        Path path = Paths.get(configPath);
        if (!Files.isRegularFile(path)) {
            Path example = Paths.get("pixel8a-java", "config.example.properties");
            if (!Files.isRegularFile(example)) throw new IOException("Missing configuration: " + path);
            path = example;
        }
        try (InputStream in = Files.newInputStream(path)) { settings.load(in); }
        mirror = new Rectangle(number("mirror.left"), number("mirror.top"),
                number("mirror.width"), number("mirror.height"));
        if (mirror.width < 100 || mirror.height < 200)
            throw new IOException("Mirror capture rectangle is too small");
        mirrorTitle = settings.getProperty("mirror.title", "").trim();
        adbPath = settings.getProperty("adb.path", "adb").trim();
        serial = settings.getProperty("adb.serial", "").trim();
        touchX = number("touch.x");
        touchY = number("touch.y");
        if (touchX < 0 || touchY < 0) throw new IOException("Touch coordinates must be nonnegative");
        if (mirrorTitle.isEmpty()) robot = captureRobot(mirror);
    }

    private static Robot captureRobot(Rectangle area) throws IOException, AWTException {
        GraphicsDevice captureDisplay = null;
        for (GraphicsDevice display : GraphicsEnvironment.getLocalGraphicsEnvironment()
                .getScreenDevices()) {
            if (display.getDefaultConfiguration().getBounds().contains(area)) {
                captureDisplay = display;
                break;
            }
        }
        if (captureDisplay == null)
            throw new IOException("Mirror rectangle must fit entirely on one connected monitor");
        return new Robot(captureDisplay);
    }

    private Rectangle resolveMirror() throws IOException {
        if (mirrorTitle.isEmpty()) return mirror;
        Path helper = Paths.get("pixel8a-java", "window-client.ps1").toAbsolutePath();
        Process lookup = new ProcessBuilder("powershell.exe", "-NoProfile", "-ExecutionPolicy",
                "Bypass", "-File", helper.toString(), "-Title", mirrorTitle)
                .redirectErrorStream(true).start();
        try {
            if (!lookup.waitFor(5, TimeUnit.SECONDS)) {
                lookup.destroyForcibly();
                throw new IOException("Timed out locating scrcpy window");
            }
            String output = new String(lookup.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
            if (lookup.exitValue() != 0) throw new IOException(output);
            String[] parts = output.split(",");
            if (parts.length != 4) throw new IOException("Invalid scrcpy window coordinates: " + output);
            return new Rectangle(Integer.parseInt(parts[0]), Integer.parseInt(parts[1]),
                    Integer.parseInt(parts[2]), Integer.parseInt(parts[3]));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            lookup.destroyForcibly();
            throw new IOException("Interrupted while locating scrcpy window", e);
        } catch (NumberFormatException e) {
            throw new IOException("Invalid scrcpy window coordinates", e);
        }
    }

    private int number(String key) throws IOException {
        try { return Integer.parseInt(settings.getProperty(key, "").trim()); }
        catch (NumberFormatException e) { throw new IOException("Invalid " + key + " in configuration", e); }
    }

    private void preview() throws IOException, AWTException {
        Rectangle area = resolveMirror();
        BufferedImage frame = captureRobot(area).createScreenCapture(area);
        Path output = Paths.get("pixel8a-java", "preview.png");
        if (!ImageIO.write(frame, "png", output.toFile()))
            throw new IOException("Could not save capture preview");
        Pixel8aVision.Observation found = vision.analyze(frame);
        System.out.println("Saved " + output.toAbsolutePath());
        System.out.println("Captured " + area);
        System.out.printf("gameplay=%s scooter=%s gaps=%d selected=%s%n",
                found.gameplay, found.scooter != null, found.gaps.size(),
                found.activeGap != null);
    }

    private void start() throws IOException, AWTException {
        if (running.get()) { System.out.println("Already running"); return; }
        if (worker != null && worker.isAlive()) {
            System.out.println("Previous input command is still finishing; wait before starting again.");
            return;
        }
        Rectangle area = resolveMirror();
        Robot capture = captureRobot(area);
        Pixel8aAdb adb = new Pixel8aAdb(adbPath, serial);
        String connected = adb.connect();
        mirror = area;
        robot = capture;
        planner.reset();
        frames = 0;
        taps = 0;
        running.set(true);
        worker = new Thread(() -> loop(adb), "Pixel8a scan and tap");
        worker.setDaemon(true);
        worker.start();
        System.out.println("ADB connected to " + connected + ". Scanning " + mirror
                + "; type stop to disable taps.");
    }

    private void loop(Pixel8aAdb adb) {
        try (Pixel8aAdb input = adb) {
            while (running.get()) {
                long started = System.nanoTime();
                BufferedImage frame = robot.createScreenCapture(mirror);
                Pixel8aVision.Observation found = vision.analyze(frame);
                frames++;
                status = found.gameplay
                        ? "scooter=" + (found.scooter != null) + " gaps=" + found.gaps.size()
                          + " selected=" + (found.activeGap != null)
                        : "waiting for gameplay";
                if (planner.shouldTap(found, System.nanoTime(), frame.getWidth(), frame.getHeight())
                        && running.get()) {
                    lastTapMs = input.tap(touchX, touchY);
                    taps++;
                }
                long elapsed = System.nanoTime() - started;
                long sleepMs = Math.max(0, 16 - elapsed / 1_000_000);
                if (sleepMs > 0) Thread.sleep(sleepMs);
            }
        } catch (Exception e) {
            status = "Stopped: " + e.getMessage();
            System.out.println(status);
        } finally {
            running.set(false);
            planner.reset();
        }
    }

    private void stop() {
        running.set(false);
        Thread active = worker;
        if (active != null) {
            try { active.join(4000); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            if (active.isAlive()) System.out.println("Waiting for an in-flight ADB command to finish.");
        }
        System.out.println("Input stopped. " + status);
    }

    public void run() throws IOException {
        System.out.println("Pixel 8a Java scan-line mode. Commands: preview, start, status, stop, quit");
        System.out.println(mirrorTitle.isEmpty() ? "Capture rectangle: " + mirror
                : "Mirror window title: " + mirrorTitle);
        BufferedReader console = new BufferedReader(new InputStreamReader(
                System.in, StandardCharsets.UTF_8));
        while (true) {
            System.out.print("Pixel8a> ");
            String line = console.readLine();
            if (line == null) { stop(); return; }
            switch (line.trim().toLowerCase()) {
                case "preview":
                    try { preview(); } catch (Exception e) { System.out.println(e.getMessage()); }
                    break;
                case "start":
                    try { start(); } catch (Exception e) { System.out.println("Start failed: " + e.getMessage()); }
                    break;
                case "status":
                    System.out.printf("running=%s frames=%d taps=%d lastADB=%d ms %s%n",
                            running.get(), frames, taps, lastTapMs, status);
                    break;
                case "stop": stop(); break;
                case "quit": stop(); return;
                default: System.out.println("Commands: preview, start, status, stop, quit");
            }
        }
    }
}
