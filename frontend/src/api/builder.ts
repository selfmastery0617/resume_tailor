import axios from "axios";
import { BACKEND_URL } from "../config";
import type { TemplateLayout } from "../resume/LayoutRenderer";
import type { ResumeStyle, TemplateDefinition } from "../resume/types";

export async function fetchDefaultLayout(): Promise<TemplateLayout> {
  const response = await axios.get<TemplateLayout>(`${BACKEND_URL}/api/templates/default-layout`);
  return response.data;
}

export async function createTemplate(payload: {
  name: string;
  description?: string;
  layout?: TemplateLayout;
  defaultStyle?: Partial<ResumeStyle>;
  duplicateOf?: string;
}): Promise<TemplateDefinition> {
  const response = await axios.post<TemplateDefinition>(`${BACKEND_URL}/api/templates`, payload);
  return response.data;
}

export async function updateTemplate(
  templateId: string,
  patch: {
    name?: string;
    description?: string;
    layout?: TemplateLayout;
    defaultStyle?: Partial<ResumeStyle>;
  },
): Promise<TemplateDefinition> {
  const response = await axios.put<TemplateDefinition>(
    `${BACKEND_URL}/api/templates/${templateId}`,
    patch,
  );
  return response.data;
}

export async function deleteTemplate(templateId: string): Promise<void> {
  await axios.delete(`${BACKEND_URL}/api/templates/${templateId}`);
}
