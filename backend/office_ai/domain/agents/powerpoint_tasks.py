"""Allow-listed tasks for PowerPoint presentations."""

from office_ai.domain.agents.tasks import AgentTaskDefinition

AGENT_ID = "powerpoint-presentations"
TASKS = (
    AgentTaskDefinition(AGENT_ID, "outline-slides", "Составить план слайдов", "Подготовка структуры презентации по выбранным материалам и инструкции.", ("document_text", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "draft-speaker-notes", "Подготовить заметки докладчика", "Черновик заметок по выбранному содержимому презентации.", ("presentation_content", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "draft-presentation", "Собрать презентацию", "Подготовка чернового содержимого презентации из выбранных материалов.", ("presentation_content", "document_text", "user_instruction")),
)
