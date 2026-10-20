"""Shared immutable metadata type for the prepared agent modules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDescriptor:
    id: str
    title: str
    description: str
    status: str = "prepared"
