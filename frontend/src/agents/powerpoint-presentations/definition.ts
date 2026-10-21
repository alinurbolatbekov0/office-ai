import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "powerpoint-presentations",
  symbol: "▰",
  heading: "Создание презентаций",
  intro: "Подготовка структуры выступления, тезисов и материалов для будущей презентации PowerPoint.",
  inputLabel: "Тема и исходные материалы",
  inputDescription: "В дальнейшем здесь можно будет задать аудиторию, цель, желаемую длину и выбрать документы.",
  plannedTasks: ["Составить план слайдов", "Подготовить тезисы и заметки докладчика", "Собрать презентацию из согласованных материалов"],
  resultLabel: "Структура презентации",
  resultDescription: "Черновой результат будет сохранён отдельно, чтобы исходные документы не менялись.",
};
