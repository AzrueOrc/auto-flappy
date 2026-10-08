# Pixel 8a Java scan-line mode

This mode adapts the original Java AutoFlappy algorithm to the green scooter and brick pillars on a Pixel 8a. It retains the scan-line idea and height target, but scans the visible scrcpy mirror and sends taps to the phone through a persistent ADB shell. The original desktop mode is unchanged.

## Run from Command Prompt

1. Install a JDK, Android platform tools, and scrcpy. Connect and unlock the Pixel, enable USB debugging, then confirm that `adb devices` lists it as `device`.
2. Open the game in a visible scrcpy window titled `FlappyFeed`. If scrcpy is on `PATH`, run `scrcpy --window-title FlappyFeed --max-size 1024 --max-fps 60`. Keep the window visible while the Java mode runs.
3. Copy `pixel8a-java\config.example.properties` to `pixel8a-java\config.local.properties`. Set `mirror.title` to the exact scrcpy window title. The Java mode will locate the game image automatically and refuse to start when that window is missing. The fixed rectangle fields are used only when `mirror.title` is blank. Set `adb.path` if `adb` is not on `PATH`; set `adb.serial` when more than one device is connected. The local file is ignored by Git.
4. From the repository root, compile and run:

   ```bat
   javac -d build\pixel8a-classes src\autoflappy\*.java
   java -cp build\pixel8a-classes autoflappy.Main --pixel8a
   ```

5. Type `preview` before `start`. Open `pixel8a-java\preview.png` and make sure it contains only the full game image, with the scooter and pillars in the expected positions. `preview` is ignored by Git.

`Start Pixel8a Java.cmd` compiles and launches the mode. It uses the JDK on `PATH`, or Android Studio's bundled JDK when `javac` is not on `PATH`.

## Controls

- `start`: connect to the selected ADB device and begin scanning. No tap is sent before this command.
- `status`: show frames, taps, last ADB command time, and detection state.
- `stop`: disable new taps and wait for any in-flight command to finish.
- `quit`: stop and exit.
- `mark-scooter X`, then `mark-gap X Y`: select the scooter lane and the center of the next pillar opening in mirror pixels. Mark each next pillar after the previous one clears.
- `clear-marks`: return to automatic gap selection.

The detector looks for the green scooter in its left-side lane and for tan brick pillar pairs with dark caps and side borders. It rejects tan background buildings without both pillar rims. It keeps the current opening until the scooter's trailing edge clears it, and briefly estimates a gap for up to 200 ms after three consistent sightings. It requires a moving, stable pillar target before tapping.

The planner insets 15% from each pillar edge, aims for the opening midpoint, and starts a flap in the lower click region. It sends one flap per entry into that region, rearms after the scooter returns to the upper region or a new pillar arrives, and enforces at least 110 ms between commands. ADB command completion can make the actual spacing longer. It waits through pause and results screens; it does not restart the game.

The sample touch point `(540, 1200)` is for a 1080-pixel-wide Pixel 8a screen. Verify that this is a safe tappable point in the game. The controller does not read scores or submit leaderboard entries. Its detection and timing need a live Pixel 8a run before performance can be claimed.

The separate [Python dashboard](../pixel8a/README.md) remains available for visual overlays, manual gap marks, and frame metrics.
