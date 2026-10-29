import { resourcePush } from '../../resource-push/boot';
import * as api from './pack-skills-api';

export const PACK_TOPICS = ['pack_skills', 'local_skills'] as const;
const POLL_MS = 15000;

export const data = $state({
  status: 'loading' as 'loading' | 'ready' | 'error',
  error: '',
  view: null as api.PackSkills | null,
  query: '',
  inventory: false,
});

export async function refresh(): Promise<void> {
  try {
    data.view = await api.getPackSkills(data.inventory);
    data.status = 'ready';
    data.error = '';
  } catch (error) {
    data.status = 'error';
    data.error = error instanceof Error ? error.message : String(error);
  }
}

export function follow(): () => void {
  void refresh();
  const stopPush = resourcePush().pushOrPoll(() => void refresh(), POLL_MS, PACK_TOPICS);
  const onFocus = (): void => void refresh();
  window.addEventListener('focus', onFocus);
  return () => {
    stopPush();
    window.removeEventListener('focus', onFocus);
  };
}
