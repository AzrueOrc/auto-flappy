from pathlib import Path

from flappy.settings import load_settings


if __name__ == "__main__":
    from flappy.window import run_app

    config_dir = Path(__file__).parent / "config"
    local_settings = config_dir / "settings.local.json"
    example_settings = config_dir / "settings.example.json"
    run_app(load_settings(local_settings if local_settings.exists() else example_settings))
