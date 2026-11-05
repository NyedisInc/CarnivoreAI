
import { clearUnsaved, NoteStore } from './note-store.svelte';
import { keyedLeases } from './shared-resource';

export type { Conflict, LoadState, NoteState, SaveState } from './note-store.svelte';
export { AUTOSAVE_MS, NOTE_CHANGED_FRAME, NoteStore } from './note-store.svelte';

const stores = keyedLeases<string, NoteStore>({
  make(name) {
    const store = new NoteStore();
    void store.open(name);
    return store;
  },
  async onLast(store) {
    await store.flush();
    store.holdUnsaved();
  },
  dispose: (store) => store.dispose(),
});

const NONE = new NoteStore();

export function acquire(name: string): NoteStore {
  const key = (name ?? '').trim();
  return key ? stores.hold(key) : NONE;
}

export async function release(name: string): Promise<void> {
  await stores.release((name ?? '').trim());
}

export async function saveAll(): Promise<void> {
  await Promise.all(stores.values().map((store) => store.save()));
}

export function reset(): void {
  for (const store of stores.values()) store.reset();
  stores.clear();
  clearUnsaved();
  NONE.reset();
}
