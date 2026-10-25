from pathlib import Path

from platformdirs import user_data_path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    dta_data_dir: Path = user_data_path("DriveTransferAgent", appauthor=False)
    dta_port: int = 8765
    agent_model: str = "gemini-flash-latest"
    google_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    rclone_bin: str = ""
    dta_master_key: str = ""
    dta_reserve_bytes: int = 1024**3

    @property
    def data(self) -> Path:
        return self.dta_data_dir

    def initialize(self):
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("logs", "tmp", "bin"):
            (self.data / name).mkdir(exist_ok=True, mode=0o700)
