"""Use cases for reading and updating local application preferences."""

from office_ai.domain.settings import SettingValue
from office_ai.infrastructure.database import LocalDatabase


def read_settings(database: LocalDatabase) -> dict[str, SettingValue]:
    return database.get_settings()


def update_setting(database: LocalDatabase, key: str, value: object) -> dict[str, SettingValue]:
    return database.update_setting(key, value)
