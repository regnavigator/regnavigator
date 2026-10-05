/**
 * 직무(task) 템플릿 클라이언트 — 기능연계를 이름 붙여 저장·목록·이름변경·삭제 (2026-10-06).
 * 백엔드: /task-templates (user 스코프, `routes/task_templates.py`).
 */

import { apiFetch } from "@/lib/api/client";

export type TaskTemplateStep = { fn: string; confidential: boolean };

export type TaskTemplate = {
  id: string;
  name: string;
  steps: TaskTemplateStep[];
  created_at: string;
  updated_at: string;
};

export async function listTaskTemplates(): Promise<TaskTemplate[]> {
  const res = await apiFetch<{ items: TaskTemplate[] }>("/task-templates");
  return res.items ?? [];
}

export async function createTaskTemplate(
  name: string,
  steps: TaskTemplateStep[],
): Promise<TaskTemplate> {
  return apiFetch<TaskTemplate>("/task-templates", {
    method: "POST",
    body: JSON.stringify({ name, steps }),
  });
}

export async function renameTaskTemplate(id: string, name: string): Promise<void> {
  await apiFetch(`/task-templates/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function deleteTaskTemplate(id: string): Promise<void> {
  await apiFetch(`/task-templates/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** 직무 템플릿이 바뀌었다 — 첫 화면 타일·패널이 다시 읽는다. */
export const TASK_TEMPLATES_CHANGED_EVENT = "regnav:task-templates-changed";
