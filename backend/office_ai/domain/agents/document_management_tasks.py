"""Allow-listed tasks for the document-management agent."""

from office_ai.domain.agents.tasks import AgentTaskDefinition

AGENT_ID = "document-management"
TASKS = (
    AgentTaskDefinition(AGENT_ID, "prepare-from-template", "Подготовить документ по шаблону", "Создание черновика документа по выбранному шаблону и материалам.", ("document_text", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "consolidate-files", "Собрать сведения из файлов", "Сведение только выбранных пользователем сведений в отдельный черновик.", ("document_text", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "check-completeness", "Проверить комплектность материалов", "Проверка наличия указанных пользователем документов и сведений.", ("document_text", "document_metadata", "user_instruction")),
)
