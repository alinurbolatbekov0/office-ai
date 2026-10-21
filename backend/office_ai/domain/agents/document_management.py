"""Prepared agent descriptor for document management."""

from office_ai.domain.agents.models import AgentDescriptor

AGENT = AgentDescriptor(
    id="document-management",
    title="Документооборот",
    description="Черновики документов, сводки и проверка материалов по выбранным файлам.",
)
