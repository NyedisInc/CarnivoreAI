
import { clearUnsaved, NoteStore } from './note-store.svelte';

export type { Conflict, LoadState, NoteState, SaveState } from './note-store.svelte';
export { AUTOSAVE_MS, NOTE_CHANGED_FRAME, NoteStore } from './note-store.svelte';

interface Held {
  store: NoteStore;
  holders: number;
}

const held = new Map<string, Held>();

const NONE = new NoteStore();

export function acquire(name: string): NoteStore {
  const key = (name ?? '').trim();
  if (!key) return NONE;
  let entry = held.get(key);
  if (!entry) {
    entry = { store: new NoteStore(), holders: 0 };
    held.set(key, entry);
    void entry.store.open(key);
  }
  entry.holders += 1;
  return entry.store;
}

export async function release(name: string): Promise<void> {
  const key = (name ?? '').trim();
  const entry = held.get(key);
  if (!entry) return;
  entry.holders -= 1;
  if (entry.holders > 0) return;
  await entry.store.flush();
  entry.store.holdUnsaved();
  if (entry.holders === 0 && held.get(key) === entry) {
    entry.store.dispose();
    held.delete(key);
  }
}

export async function saveAll(): Promise<void> {
  await Promise.all([...held.values()].map((entry) => entry.store.save()));
}

export function reset(): void {
  for (const entry of held.values()) {
    entry.store.reset();
    entry.store.dispose();
  }
  held.clear();
  clearUnsaved();
  NONE.reset();
}
