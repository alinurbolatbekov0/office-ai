import type { AgentScreenDefinition } from "../shared/types";

export const definition: AgentScreenDefinition = {
  id: "business-correspondence",
  symbol: "✉",
  heading: "Подготовка деловой переписки",
  intro: "Черновики деловых писем, ответов и сопроводительных текстов на русском и казахском языках.",
  inputLabel: "Контекст и материалы",
  inputDescription: "Выберите исходное письмо или документ и укажите адресата, тему и язык черновика.",
  plannedTasks: ["Составить черновик письма", "Подготовить ответ на входящее обращение", "Сформировать сопроводительный текст"],
  resultLabel: "Черновик письма",
  resultDescription: "Программа подготовит файл для проверки пользователем. Отправки писем из приложения не будет.",
};
