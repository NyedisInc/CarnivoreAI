import { authFetch } from '../../opscenter/api/auth.svelte';
import { refusalText } from '../automations/format';

export async function focusTaskManagerItem(list: string, id: number): Promise<string | null> {
  try {
    await authFetch('/cplugs/huddle/focus', { method: 'POST', body: JSON.stringify({ list, items: [id], open: id }) });
  } catch (error) {
    return refusalText(error);
  }
  return null;
}
