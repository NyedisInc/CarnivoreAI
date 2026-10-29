import { t } from '../sdk';
import { AGGREGATE, ALL_LIST, isAgentList, listFallback, type TaskManagerListRow } from './huddle-model';

export const SCHEDULE_PROJECT_KEY = 'cloude.huddle.scheduleProject';

export function projectChoices<T extends Pick<TaskManagerListRow, 'key'>>(lists: readonly T[]): T[] {
  return lists.filter((row) => row.key !== AGGREGATE && !isAgentList(row.key));
}

export function rememberedProject(): string | null {
  try {
    return globalThis.localStorage?.getItem(SCHEDULE_PROJECT_KEY) ?? null;
  } catch {
    return null;
  }
}

export function rememberProject(key: string): void {
  try {
    globalThis.localStorage?.setItem(SCHEDULE_PROJECT_KEY, key);
  } catch {
  }
}

export function defaultProject(requested: string, lists: readonly Pick<TaskManagerListRow, 'key'>[], remembered: string | null): string {
  const keys = projectChoices(lists).map((row) => row.key);
  if (keys.includes(requested)) return requested;
  if (remembered !== null && keys.includes(remembered)) return remembered;
  return keys.find((key) => key !== ALL_LIST) ?? keys[0] ?? requested;
}

/* label: " */
export function listLabel(key: string, name: string | null): string {
  if (key === ALL_LIST) return t('cplug.huddle.list.shared');
  if (name) return name;
  const fallback = listFallback(key);
  return t(fallback.key, { id: fallback.id });
}
