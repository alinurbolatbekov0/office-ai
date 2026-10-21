import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "document-management",
  symbol: "▤",
  heading: "Помощник по документам",
  intro: "Просмотрите локальные DOCX и PDF, подготовьте перечень документов или черновик на основе выбранных материалов.",
  inputLabel: "Документы и шаблоны",
  inputDescription: "Выберите DOCX или PDF и сформулируйте, какой черновик или проверку подготовить.",
  plannedTasks: ["Подготовить документ по шаблону", "Собрать сведения из нескольких файлов", "Проверить комплектность материалов"],
  resultLabel: "Подготовленный документ",
  resultDescription: "Результат будет создан отдельным файлом. Оригиналы останутся без изменений.",
};
