# Pixel 8a scooter autopilot

This Windows dashboard watches a Pixel 8a game through scrcpy, recognizes the green scooter and brick pillar openings, and sends optional ADB taps. It is a separate adaptation in this fork; the original Java program remains under `src/`.

## Set up in Command Prompt

1. Install Python 3.12 or newer, Android platform tools (`adb`), and scrcpy. Put `adb` and `scrcpy` on `PATH`, or set their full paths in `config/settings.local.json`.
2. Connect the Pixel by USB, enable USB debugging, unlock it, and run `adb devices`. It must be listed as `device`.
3. Open Command Prompt in this `pixel8a` directory, then run:

   ```bat
   py -3 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe main.py
   ```

   After installation, `Start Pixel 8a Autopilot.cmd` runs the last command.

The app uses `config/settings.example.json` until you create `config/settings.local.json`. Copy the example to the local file to set your device serial, tool paths, video codec, mirror placement, and tap coordinates. The local file is ignored by Git. If one ADB device is attached, `serial` may be empty. The default `(540, 1200)` touch point is for a 1080-pixel-wide Pixel 8a screen; verify that it lands in the game's tappable area. Window capture follows the scrcpy client area, so the sample crop rectangle is ignored while `use_scrcpy_window` is true.

## Playing and stopping

The dashboard connects ADB and starts capture, but does not tap until you check **Enable Autopilot** or deliberately enable and press **TEST FLAP**. Autopilot remains armed through pause and results screens and waits for gameplay to return. It does not restart the game. **STOP INPUT** disables further commands until you connect ADB again.

The red outline is the selected pillar opening. Cyan horizontal lines sit 15% of the opening height inside each pillar edge; the white line is its midpoint. The green upper band means no click and the red lower band is the click area. The planner sends at most one tap while the scooter remains in a red band. It rearms only after the scooter returns to green or a new pillar is selected, subject to a 110 ms minimum tap interval and ADB command completion. Three blue vertical lines show the behind, scooter, and approaching scan columns.

For the optional two-point overlay, click **Mark scooter**, then click the scooter in the dashboard image. Click **Mark next gap center**, then the center of each new pillar opening. While this mode is active, the planner waits for a new gap mark after the current pillar clears. **Clear points / automatic gaps** returns to automatic selection. A verified gap can be projected through a detector dropout for at most 200 ms; `gap estimated` appears in the metrics line during that time.

These thresholds came from recorded Pixel 8a frames and offline checks. Gap detection and flap timing still need live validation for this specific game. The dashboard does not track scores or submit leaderboard entries.

## Tests

Run `.venv\Scripts\python.exe -m unittest discover -s tests -v`. The committed tests use synthetic data and do not need a connected phone. The original local development session also used private recorded game frames for detector regression checks; those recordings are not included in this public fork.

This fork retains the repository's GPL-3.0 license.
