"""Allow-listed task definitions for the independent AI-agent modules."""

from __future__ import annotations

from dataclasses import dataclass

from office_ai.domain.agents.consent import ALLOWED_DATA_CATEGORIES


@dataclass(frozen=True)
class AgentTaskDefinition:
    agent_id: str
    code: str
    title: str
    purpose: str
    allowed_categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_categories, tuple):
            object.__setattr__(self, "allowed_categories", tuple(self.allowed_categories))
        if not self.agent_id or not self.code or not self.title or not self.purpose:
            raise ValueError("Для задачи агента обязательны идентификатор и описание.")
        if (
            not self.allowed_categories
            or len(self.allowed_categories) != len(set(self.allowed_categories))
            or not set(self.allowed_categories).issubset(ALLOWED_DATA_CATEGORIES)
        ):
            raise ValueError("Для задачи заданы неизвестные категории данных.")

