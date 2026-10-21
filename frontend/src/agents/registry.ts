import { definition as documentManagement } from "./document-management/definition";
import { definition as businessCorrespondence } from "./business-correspondence/definition";
import { definition as excelAnalytics } from "./excel-analytics/definition";
import { definition as powerpointPresentations } from "./powerpoint-presentations/definition";

export const definitions = {
  [documentManagement.id]: documentManagement,
  [businessCorrespondence.id]: businessCorrespondence,
  [excelAnalytics.id]: excelAnalytics,
  [powerpointPresentations.id]: powerpointPresentations,
};
