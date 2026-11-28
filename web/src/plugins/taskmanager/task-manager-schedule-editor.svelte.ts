import { authFetch } from '../sdk';
import { huddle, write } from './huddle.svelte';
import { defaultProject, rememberedProject, rememberProject } from './task-manager-schedule-project';
import { addBody, editBody, type EditorDraft } from './task-manager-schedule';
import type { HuddleItem } from './huddle-model';

export const scheduleEditor = $state<{ open: boolean; list: string; item: HuddleItem | null }>({ open: false, list: 'all', item: null });

export function openScheduleEditor(list: string, item: HuddleItem | null = null): void {
  scheduleEditor.list = item?.list ?? defaultProject(list, huddle.lists, rememberedProject());
  scheduleEditor.item = item;
  scheduleEditor.open = true;
}

export function pickEditorProject(key: string): void {
  scheduleEditor.list = key;
  rememberProject(key);
}

export function closeScheduleEditor(): void {
  scheduleEditor.open = false;
}

const runNow = (id: number): Promise<unknown> => authFetch(`/cplugs/huddle/items/${id}/run-now`, { method: 'POST' });

export async function saveEditor(draft: EditorDraft): Promise<boolean> {
  const item = scheduleEditor.item;
  if (item) {
    const body = editBody(item, draft, true);
    if (!body) return false;
    if (!Object.keys(body).length) return true;
    return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ ...body, expected_revision: item.revision }) }));
  }
  const body = addBody(draft, true);
  if (!body) return false;
  return write(() => authFetch(`/cplugs/huddle/lists/${encodeURIComponent(scheduleEditor.list)}/items`, { method: 'POST', body: JSON.stringify(body) }));
}

export async function runEditorNow(draft: EditorDraft): Promise<boolean> {
  const item = scheduleEditor.item;
  if (item) {
    const body = editBody(item, draft, item.start_trigger !== null && item.start_trigger !== undefined);
    if (!body) return false;
    return write(async () => {
      if (Object.keys(body).length) await authFetch(`/cplugs/huddle/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ ...body, expected_revision: item.revision }) });
      await runNow(item.id);
    });
  }
  const body = addBody(draft, draft.plan.kind !== 'none');
  if (!body) return false;
  return write(async () => {
    const added = (await authFetch(`/cplugs/huddle/lists/${encodeURIComponent(scheduleEditor.list)}/items`, { method: 'POST', body: JSON.stringify(body) })) as { id: number };
    await runNow(added.id);
  });
}
