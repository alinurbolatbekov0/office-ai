"""Prepared agent descriptor for business correspondence."""

from office_ai.domain.agents.models import AgentDescriptor

AGENT = AgentDescriptor(
    id="business-correspondence",
    title="Деловая переписка",
    description="Черновики деловых писем, ответов и сопроводительных текстов без отправки.",
)
