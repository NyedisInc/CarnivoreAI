import { authFetch, familyOf, resourcePush, taskManagerView, type TaskManagerFold } from '../sdk';

export const COMMAND_FAMILY = 'cplug.tmdevtools.command';

export interface DevCommand {
  seq: number;
  kind: 'scroll_top' | 'fold';
  list?: string | null;
  action?: TaskManagerFold['action'];
  items?: number[];
  groups?: number[];
  project?: string | null;
}

let applied: number | null = null;
let started = false;
let reading = false;

export async function applyCommand(command: DevCommand): Promise<void> {
  const view = taskManagerView();
  if (!view) return;
  if (command.kind === 'scroll_top') await view.scrollTop(command.list ?? null);
  else if (command.kind === 'fold' && command.action) {
    await view.fold({ action: command.action, items: command.items ?? [], groups: command.groups ?? [], project: command.project ?? null });
  }
}

export async function readCommands(): Promise<void> {
  if (reading) return;
  reading = true;
  try {
    const path = applied === null ? '/cplugs/tmdevtools/commands' : `/cplugs/tmdevtools/commands?after=${applied}`;
    let body = await authFetch<{ commands?: DevCommand[]; latest?: number }>(path);
    if (applied !== null && (body.latest ?? 0) < applied) {
      applied = 0;
      body = await authFetch<{ commands?: DevCommand[]; latest?: number }>('/cplugs/tmdevtools/commands?after=0');
    }
    for (const command of body.commands ?? []) {
      applied = Math.max(applied ?? 0, command.seq);
      await applyCommand(command);
    }
    applied = Math.max(applied ?? 0, body.latest ?? 0);
  } catch (error) {
    console.warn('tmdevtools: could not read the commands', error);
  } finally {
    reading = false;
  }
}

export function startCommands(): void {
  if (started) return;
  started = true;
  resourcePush().onChange((topics) => {
    if (topics.some((topic) => familyOf(topic) === COMMAND_FAMILY)) void readCommands();
  });
  void readCommands();
}

export function resetCommands(): void {
  applied = null;
  started = false;
  reading = false;
}
