"""Independent, UI-only agent descriptors for the initial scaffold."""

from office_ai.domain.agents.catalog import get_agent_descriptors
from office_ai.domain.agents.models import AgentDescriptor

__all__ = ["AgentDescriptor", "get_agent_descriptors"]
