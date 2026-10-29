import * as api from './mods-api';
import { groupProblems, refusalText } from './mods-format';
import { refresh } from './store.svelte';

export function createModActions(): {
  readonly busyId: string | null;
  readonly notice: string;
  toggle(mod: api.ModEntry, next: boolean): void;
  remove(mod: api.ModEntry): void;
} {
  let busyId = $state<string | null>(null);
  let notice = $state('');

  async function act(id: string, call: () => Promise<unknown>): Promise<void> {
    busyId = id;
    notice = '';
    try {
      const answer = (await call()) as api.WriteResult | undefined;
      const bad = groupProblems(answer?.results ?? []);
      if (bad.length) notice = bad.join(' ');
    } catch (error) {
      notice = refusalText(error);
    } finally {
      busyId = null;
    }
    await refresh();
  }

  return {
    get busyId() { return busyId; },
    get notice() { return notice; },
    toggle(mod, next): void {
      void act(mod.mod_id, () => api.setEnabled(mod.mod_id, next));
    },
    remove(mod): void {
      const call = mod.source === 'catalog' && mod.install_id ? () => api.uninstallCatalog(mod.install_id!) : () => api.removeLocal(mod.mod_id);
      void act(mod.mod_id, call);
    },
  };
}
