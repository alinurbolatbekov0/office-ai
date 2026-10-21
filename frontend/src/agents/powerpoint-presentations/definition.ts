import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "powerpoint-presentations",
  symbol: "▰",
  heading: "Создание презентаций",
  intro: "Просмотрите текст и заметки PPTX и подготовьте план слайдов, заметки докладчика или черновик презентации.",
  inputLabel: "Тема и исходные материалы",
  inputDescription: "Выберите исходную презентацию или документ и опишите аудиторию, цель и желаемую длину.",
  plannedTasks: ["Составить план слайдов", "Подготовить тезисы и заметки докладчика", "Собрать презентацию из согласованных материалов"],
  resultLabel: "Структура презентации",
  resultDescription: "Черновой результат будет сохранён отдельно, чтобы исходные документы не менялись.",
};
