"""Allow-listed tasks for business correspondence."""

from office_ai.domain.agents.tasks import AgentTaskDefinition

AGENT_ID = "business-correspondence"
TASKS = (
    AgentTaskDefinition(AGENT_ID, "draft-letter", "Составить черновик письма", "Подготовка черновика письма на основе инструкции и выбранных материалов.", ("document_text", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "draft-reply", "Подготовить ответ", "Подготовка черновика ответа на выбранное обращение.", ("document_text", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "draft-cover-note", "Сформировать сопроводительный текст", "Подготовка текста сопровождения для выбранных пользователем материалов.", ("document_text", "document_metadata", "user_instruction")),
)
