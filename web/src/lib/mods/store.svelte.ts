import { resourcePush } from '../resource-push/boot';
import * as api from './mods-api';
import { refusalText } from './mods-format';

export const MODS_TOPICS = ['mods', 'catalog'] as const;
const POLL_MS = 15000;

export const data = $state({
  status: 'loading' as 'loading' | 'ready' | 'error',
  error: '',
  list: null as api.ModsResponse | null,
});

export async function refresh(): Promise<void> {
  try {
    data.list = await api.listMods();
    data.status = 'ready';
    data.error = '';
  } catch (error) {
    data.status = 'error';
    data.error = refusalText(error);
  }
}

export function follow(): () => void {
  void refresh();
  return resourcePush().pushOrPoll(() => void refresh(), POLL_MS, MODS_TOPICS);
}
