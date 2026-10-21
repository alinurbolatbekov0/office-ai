import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "excel-analytics",
  symbol: "▥",
  heading: "Аналитика таблиц Excel",
  intro: "Будущая рабочая область для исследования таблиц, поиска закономерностей и подготовки выводов.",
  inputLabel: "Таблицы для анализа",
  inputDescription: "Можно будет выбрать XLSX-файлы из библиотеки. Макросы и встроенный код запускаться не будут.",
  plannedTasks: ["Сделать сводку по таблице", "Сравнить показатели и периоды", "Подготовить выводы для отчёта"],
  resultLabel: "Сводка и выводы",
  resultDescription: "Результаты анализа будут показаны отдельно и не изменят исходную таблицу.",
};
