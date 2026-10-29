
export const TASK_MANAGER_SEEN_KEY = 'carnivore.huddle.seen';

function read(key: string): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
  } catch (err) {
    console.warn('huddle: could not remember the tab', err);
  }
}

export const taskManagerUi = $state<{ seen: number }>({
  seen: Number(read(TASK_MANAGER_SEEN_KEY)) || 0,
});

export function markTaskManagerSeen(seq: number): void {
  if (seq <= taskManagerUi.seen) return;
  taskManagerUi.seen = seq;
  write(TASK_MANAGER_SEEN_KEY, String(seq));
}

export function reloadTaskManagerUi(): void {
  taskManagerUi.seen = Number(read(TASK_MANAGER_SEEN_KEY)) || 0;
}
