"""Application preferences that are safe to persist in SQLite."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

Theme: TypeAlias = Literal["light", "dark"]
SettingValue: TypeAlias = Theme | bool

DEFAULT_SETTINGS: Final[dict[str, SettingValue]] = {
    "theme": "light",
    "confirm_destructive_actions": True,
}


class InvalidSetting(ValueError):
    """Raised when a setting key or value is outside the supported contract."""


def validate_setting(key: str, value: object) -> SettingValue:
    if key == "theme" and isinstance(value, str) and value in {"light", "dark"}:
        return value  # type: ignore[return-value]
    if key == "confirm_destructive_actions" and type(value) is bool:
        return value
    raise InvalidSetting(f"Unsupported setting or value: {key}")
