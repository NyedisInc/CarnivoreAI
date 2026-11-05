import { t } from '../sdk';
import { createAddFiles, type AddFiles } from './task-manager-add-files.svelte';
import { addItem, huddle } from './huddle.svelte';
import { AGGREGATE, ALL_LIST, isAgentList, wholeEntry, type TaskManagerListRow } from './huddle-model';
import { listLabel } from './task-manager-schedule-project';
import { submitNow } from './task-submit';
import { createSentFlash, submitLook } from './task-submit-state.svelte';

export const MULTILINE_ROWS = 5;

export interface AddRow {
  draft: string;
  readonly multiline: boolean;
  readonly adding: boolean;
  readonly files: AddFiles;
  readonly look: ReturnType<typeof submitLook>;
  readonly targets: Pick<TaskManagerListRow, 'key' | 'name'>[];
  readonly placeholder: string;
  add(): Promise<void>;
  onLineKey(event: KeyboardEvent): void;
  onAreaKey(event: KeyboardEvent): void;
  toggleMultiline(): void;
}

const offered = (key: string, keep: string): boolean => !isAgentList(key) || key === keep;

export function createAddRow(pin: () => { pinnedList: string | null; pinnedAll: boolean }): AddRow {
  let draft = $state('');
  let multiline = $state(false);
  let adding = $state(false);
  const files = createAddFiles(() => huddle.addTarget);
  $effect(() => { void huddle.addTarget; files.followTarget(); });
  const sent = createSentFlash();
  const entry = $derived(wholeEntry(draft));
  const look = $derived(submitLook(entry.length > 0, sent.on));
  const targets = $derived<Pick<TaskManagerListRow, 'key' | 'name'>[]>(
    huddle.lists.length ? huddle.lists.filter((r) => offered(r.key, huddle.addTarget)) : [{ key: ALL_LIST, name: null }]);
  const targetName = $derived.by(() => {
    const { pinnedList, pinnedAll } = pin();
    const key = pinnedList !== null && !pinnedAll ? pinnedList : huddle.addTarget;
    if (!key || key === AGGREGATE || key === ALL_LIST) return null;
    const row = huddle.lists.find((r) => r.key === key);
    return row ? listLabel(row.key, row.name) : null;
  });
  const placeholder = $derived(targetName ? t('cplug.huddle.add.placeholder_for', { name: targetName }) : t('cplug.huddle.add.placeholder'));

  async function add(): Promise<void> {
    if (!entry || adding || files.staging) return;
    adding = true;
    const save = async (): Promise<boolean> => {
      const outcome = await addItem(entry, files.attached.ids); // the server did not answer
      adding = false;
      if (outcome !== 'failed') { draft = ''; files.attached.clear(); sent.flash(); }
      return outcome === 'added';
    };
    try {
      await submitNow(huddle.addTarget, save);
    } finally {
      adding = false;
    }
  }

  return {
    get draft() { return draft; },
    set draft(value: string) { draft = value; },
    get multiline() { return multiline; },
    get adding() { return adding; },
    files,
    get look() { return look; },
    get targets() { return targets; },
    get placeholder() { return placeholder; },
    add,
    onLineKey(event) {
      if (event.key !== 'Enter' || event.isComposing || event.shiftKey) return;
      event.preventDefault();
      (event.currentTarget as HTMLInputElement).form?.requestSubmit();
    },
    onAreaKey(event) {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        void add();
      }
    },
    toggleMultiline() {
      multiline = !multiline;
      if (!multiline) draft = draft.replace(/\s*\r?\n\s*/g, ' ').trim();
    },
  };
}
