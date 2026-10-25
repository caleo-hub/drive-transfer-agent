import pytest

from drive_transfer_agent.config import Settings
from drive_transfer_agent.store import Store


class MemoryVault:
    def __init__(self):
        self.data = {}

    def read(self):
        return dict(self.data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = value


@pytest.fixture
def settings(tmp_path):
    result = Settings(dta_data_dir=tmp_path / "app", _env_file=None)
    result.initialize()
    return result


@pytest.fixture
def vault():
    return MemoryVault()


@pytest.fixture
def store(settings):
    return Store(settings.data / "test.sqlite3")
