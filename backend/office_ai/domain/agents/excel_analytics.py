"""Prepared agent descriptor for Excel analytics."""

from office_ai.domain.agents.models import AgentDescriptor

AGENT = AgentDescriptor(
    id="excel-analytics",
    title="Excel-аналитика",
    description="Сводки, сравнение периодов и черновые выводы по выбранным значениям XLSX.",
)
