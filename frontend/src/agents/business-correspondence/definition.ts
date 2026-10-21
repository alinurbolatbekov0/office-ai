import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "business-correspondence",
  symbol: "✉",
  heading: "Подготовка деловой переписки",
  intro: "Черновики деловых писем, ответов и сопроводительных текстов на русском и казахском языках.",
  inputLabel: "Контекст и материалы",
  inputDescription: "В будущем можно будет указать тему, адресата, язык и приложить документы из библиотеки.",
  plannedTasks: ["Составить черновик письма", "Подготовить ответ на входящее обращение", "Сформировать сопроводительный текст"],
  resultLabel: "Черновик письма",
  resultDescription: "Программа подготовит файл для проверки пользователем. Отправки писем из приложения не будет.",
};
