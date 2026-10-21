"""Prepared agent descriptor for PowerPoint presentations."""

from office_ai.domain.agents.models import AgentDescriptor

AGENT = AgentDescriptor(
    id="powerpoint-presentations",
    title="Презентации PowerPoint",
    description="Планы слайдов, заметки докладчика и черновики презентаций по выбранным материалам.",
)
