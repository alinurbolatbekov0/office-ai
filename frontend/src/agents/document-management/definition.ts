import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "document-management",
  symbol: "▤",
  heading: "Помощник по документам",
  intro: "Подготовка документов, работа с шаблонами и организация материалов в локальной библиотеке.",
  inputLabel: "Документы и шаблоны",
  inputDescription: "Выбор материалов из библиотеки будет доступен после подключения функций агента.",
  plannedTasks: ["Подготовить документ по шаблону", "Собрать сведения из нескольких файлов", "Проверить комплектность материалов"],
  resultLabel: "Подготовленный документ",
  resultDescription: "Результат будет создан отдельным файлом. Оригиналы останутся без изменений.",
};
