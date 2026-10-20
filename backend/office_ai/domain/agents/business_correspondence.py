"""Prepared agent descriptor for business correspondence."""

from office_ai.domain.agents.models import AgentDescriptor

AGENT = AgentDescriptor(
    id="business-correspondence",
    title="Деловая переписка",
    description="Подготовка деловых писем и ответов без их отправки.",
)
