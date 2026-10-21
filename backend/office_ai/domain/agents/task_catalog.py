"""Read-only registry and serialization for agent task allow-lists."""

from dataclasses import asdict

from office_ai.domain.agents.business_correspondence_tasks import TASKS as CORRESPONDENCE_TASKS
from office_ai.domain.agents.document_management_tasks import TASKS as DOCUMENT_TASKS
from office_ai.domain.agents.excel_analytics_tasks import TASKS as EXCEL_TASKS
from office_ai.domain.agents.powerpoint_tasks import TASKS as POWERPOINT_TASKS
from office_ai.domain.agents.tasks import AgentTaskDefinition

_TASKS: tuple[AgentTaskDefinition, ...] = (
    *DOCUMENT_TASKS,
    *CORRESPONDENCE_TASKS,
    *EXCEL_TASKS,
    *POWERPOINT_TASKS,
)
_TASK_LOOKUP = {(task.agent_id, task.code): task for task in _TASKS}
if len(_TASK_LOOKUP) != len(_TASKS):
    raise RuntimeError("В каталоге задач повторяются идентификаторы агента и задачи.")


def get_agent_task(agent_id: str, task_code: str) -> AgentTaskDefinition | None:
    return _TASK_LOOKUP.get((agent_id, task_code))


def get_agent_tasks(agent_id: str) -> tuple[AgentTaskDefinition, ...]:
    return tuple(task for task in _TASKS if task.agent_id == agent_id)


def serialize_agent_tasks(agent_id: str) -> list[dict[str, object]]:
    return [asdict(task) for task in get_agent_tasks(agent_id)]
