"""Read-only registry for the four planned agents."""

from dataclasses import asdict

from office_ai.domain.agents.business_correspondence import AGENT as business_correspondence
from office_ai.domain.agents.document_management import AGENT as document_management
from office_ai.domain.agents.excel_analytics import AGENT as excel_analytics
from office_ai.domain.agents.models import AgentDescriptor
from office_ai.domain.agents.powerpoint_presentations import AGENT as powerpoint_presentations


def get_agent_descriptors() -> tuple[AgentDescriptor, ...]:
    # The independent modules currently expose metadata only.
    return (
        document_management,
        business_correspondence,
        excel_analytics,
        powerpoint_presentations,
    )


def serialize_agent_descriptors() -> list[dict[str, str]]:
    return [asdict(agent) for agent in get_agent_descriptors()]
