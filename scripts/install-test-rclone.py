"""Install an official isolated rclone for credential-free integration tests."""

import asyncio
from pathlib import Path

from drive_transfer_agent.config import Settings
from drive_transfer_agent.rclone import Rclone

settings = Settings(dta_data_dir=Path(__file__).resolve().parents[1] / ".state" / "runtime", _env_file=None)
settings.initialize()
print(asyncio.run(Rclone(settings, None).install()))
