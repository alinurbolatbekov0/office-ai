"""Application service exposing prepared agent descriptions."""

from office_ai.domain.agents.catalog import serialize_agent_descriptors


def list_agents() -> list[dict[str, str]]:
    return serialize_agent_descriptors()
