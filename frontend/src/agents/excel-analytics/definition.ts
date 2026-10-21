import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "excel-analytics",
  symbol: "▥",
  heading: "Аналитика таблиц Excel",
  intro: "Просмотрите значения из XLSX и подготовьте сводку, сравнение периодов или выводы по выбранным данным.",
  inputLabel: "Таблицы для анализа",
  inputDescription: "Выберите XLSX из локальной библиотеки и задайте вопрос по его значениям. Макросы не выполняются.",
  plannedTasks: ["Сделать сводку по таблице", "Сравнить показатели и периоды", "Подготовить выводы для отчёта"],
  resultLabel: "Сводка и выводы",
  resultDescription: "Результаты анализа будут показаны отдельно и не изменят исходную таблицу.",
};
