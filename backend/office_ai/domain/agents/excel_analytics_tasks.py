"""Allow-listed tasks for Excel analytics."""

from office_ai.domain.agents.tasks import AgentTaskDefinition

AGENT_ID = "excel-analytics"
TASKS = (
    AgentTaskDefinition(AGENT_ID, "summarize-workbook", "Сделать сводку по таблице", "Подготовка сводки только по выбранной таблице и инструкции.", ("spreadsheet_values", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "compare-periods", "Сравнить показатели и периоды", "Сравнение выбранных пользователем показателей и периодов.", ("spreadsheet_values", "document_metadata", "user_instruction")),
    AgentTaskDefinition(AGENT_ID, "report-findings", "Подготовить выводы для отчёта", "Формирование черновых выводов по выбранным табличным данным.", ("spreadsheet_values", "user_instruction")),
)
