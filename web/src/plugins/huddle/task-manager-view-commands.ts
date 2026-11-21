import { registerTaskManagerView, type TaskManagerFold, type TaskManagerView } from '../sdk';
import { huddle, selectList, toggleRow } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';
import { groupsOf, setGroupsFolded } from './task-manager-groups.svelte';
import { SECTION_ORDER } from './task-manager-status-sections';
import { projectFoldKey, sectionFoldKey, setSectionsFolded } from './task-manager-status-folds.svelte';

const SCROLL_BOX = '[data-task-manager-scroll]';

function knownLists(): string[] {
  return [...new Set([...huddle.lists.map((row) => row.key), ...(huddle.groups ?? []).map((g) => g.list), ...(huddle.body ? [huddle.body.list] : [])])];
}

function groupsFor(ids: readonly number[] | null, list: string | null): ReturnType<typeof groupsOf> {
  const lists = list === null ? knownLists() : [list];
  return lists.flatMap((key) => groupsOf(key)).filter((g) => ids === null || ids.includes(g.id));
}

async function scrollTop(list: string | null): Promise<void> {
  if (list !== null && huddle.selected !== AGGREGATE && huddle.selected !== list) await selectList(list);
  requestAnimationFrame(() => document.querySelectorAll<HTMLElement>(SCROLL_BOX).forEach((box) => { box.scrollTop = 0; }));
}

function closeCard(only: readonly number[]): void {
  const open = huddle.openId;
  if (open !== null && (only.length === 0 || only.includes(open))) toggleRow(open);
}

async function fold(command: TaskManagerFold): Promise<void> {
  const folded = command.action !== 'unfold';
  if (command.action === 'close' || (folded && command.items.length)) closeCard(command.items);
  else if (!folded && command.items.length) {
    const target = command.items[command.items.length - 1] as number;
    if (huddle.openId !== target) toggleRow(target);
  }
  if (command.project !== null) {
    setSectionsFolded([projectFoldKey(command.project), ...SECTION_ORDER.map((section) => sectionFoldKey(command.project as string, section))], folded);
    await setGroupsFolded(groupsFor(null, command.project), folded);
  }
  if (command.groups.length) await setGroupsFolded(groupsFor(command.groups, null), folded);
}

export const taskManagerView: TaskManagerView = { scrollTop, fold };

export function startViewCommands(): void {
  registerTaskManagerView(taskManagerView);
}
