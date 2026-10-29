
export const GLOBAL_WIDGET_IDS: readonly string[] = ['task-manager-all', 'task-manager-mk2-all', 'tasks-all', 'bookmarks-all', 'pipeline', 'automations-all'];

export function isGlobalWidget(id: string | null | undefined): boolean {
  if (!id) return false;
  return GLOBAL_WIDGET_IDS.includes(id.startsWith('core.') ? id.slice(5) : id);
}
