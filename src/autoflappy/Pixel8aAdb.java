package autoflappy;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** Persistent ADB shell for single, acknowledged Pixel taps. */
public final class Pixel8aAdb implements AutoCloseable {
    private static final String CLOSED = "CODEX_FLAPPY_SHELL_CLOSED";
    private final String adb;
    private final String requestedSerial;
    private String serial;
    private Process shell;
    private BufferedWriter input;
    private BlockingQueue<String> responses = new LinkedBlockingQueue<>();
    private int commandId;

    public Pixel8aAdb(String adb, String requestedSerial) {
        this.adb = adb == null || adb.trim().isEmpty() ? "adb" : adb.trim();
        this.requestedSerial = requestedSerial == null ? "" : requestedSerial.trim();
    }

    private static List<String> lines(Process process, long timeoutMs) throws IOException {
        try {
            if (!process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                throw new IOException("ADB command timed out");
            }
            List<String> output = new ArrayList<>();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) output.add(line);
            }
            if (process.exitValue() != 0) throw new IOException("ADB command failed: " + output);
            return output;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
            throw new IOException("ADB command interrupted", e);
        }
    }

    public synchronized String connect() throws IOException {
        close();
        Process devices = new ProcessBuilder(adb, "devices").redirectErrorStream(true).start();
        List<String> available = new ArrayList<>();
        for (String line : lines(devices, 5000)) {
            String[] fields = line.trim().split("\\s+");
            if (fields.length >= 2 && fields[1].equals("device")) available.add(fields[0]);
        }
        if (requestedSerial.isEmpty()) {
            if (available.size() != 1)
                throw new IOException("Expected exactly one authorized ADB device; found " + available.size());
            serial = available.get(0);
        } else {
            if (!available.contains(requestedSerial))
                throw new IOException("Configured Pixel " + requestedSerial + " is not connected or authorized");
            serial = requestedSerial;
        }
        shell = new ProcessBuilder(adb, "-s", serial, "shell").redirectErrorStream(true).start();
        input = new BufferedWriter(new OutputStreamWriter(shell.getOutputStream(), StandardCharsets.UTF_8));
        Process activeShell = shell;
        responses = new LinkedBlockingQueue<>();
        BlockingQueue<String> responseQueue = responses;
        Thread reader = new Thread(() -> {
            try (BufferedReader out = new BufferedReader(new InputStreamReader(
                    activeShell.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = out.readLine()) != null) responseQueue.offer(line.trim());
            } catch (IOException ignored) {
                // The pending command will see CLOSED and stop input.
            } finally {
                responseQueue.offer(CLOSED);
            }
        }, "Pixel8a ADB responses");
        reader.setDaemon(true);
        reader.start();
        send(":");
        return serial;
    }

    private void send(String command) throws IOException {
        if (shell == null || !shell.isAlive() || input == null)
            throw new IOException("Persistent ADB shell is unavailable");
        String marker = "CODEX_FLAPPY_DONE_" + ++commandId;
        input.write(command);
        input.newLine();
        input.write("echo " + marker + ":$?");
        input.newLine();
        input.flush();
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (true) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) throw new IOException("ADB response timed out; tap completion unknown");
                String line = responses.poll(remaining, TimeUnit.NANOSECONDS);
                if (line == null || CLOSED.equals(line))
                    throw new IOException("ADB shell closed; tap completion unknown");
                if ((marker + ":0").equals(line)) return;
                if (line.startsWith(marker + ":"))
                    throw new IOException("ADB input command failed with status "
                            + line.substring(marker.length() + 1));
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("ADB tap interrupted; completion unknown", e);
        }
    }

    public synchronized long tap(int x, int y) throws IOException {
        if (x < 0 || y < 0) throw new IllegalArgumentException("Touch coordinates must be nonnegative");
        long start = System.nanoTime();
        send("input tap " + x + " " + y);
        return TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);
    }

    @Override public synchronized void close() {
        if (shell != null) {
            shell.destroy();
            try {
                if (!shell.waitFor(1, TimeUnit.SECONDS)) shell.destroyForcibly();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                shell.destroyForcibly();
            }
        }
        shell = null;
        input = null;
        serial = null;
        responses.clear();
    }
}
