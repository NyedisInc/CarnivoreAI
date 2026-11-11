import { authFetch } from '../../opscenter/api/auth.svelte';
import { argentCost } from './cost-store.svelte';

const wanted = new Map<symbol, number>();
const clientId = `w${Math.random().toString(36).slice(2, 12)}`;
let scheduled = false;
let sent = false;

function flush(): void {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => {
    scheduled = false;
    const rows = [...new Set(wanted.values())].map(String);
    if (rows.length === 0 && !sent) return;
    sent = rows.length > 0;
    authFetch('/argent/cost/agents/watch', { method: 'PUT', body: JSON.stringify({ client_id: clientId, row_ids: rows }) }).catch(() => undefined);
  });
}

export function useAgentWatch(row: () => number | null | undefined): void {
  const key = Symbol('agent-watch');
  $effect(() => {
    const id = row();
    argentCost().data?.as_of;
    if (typeof id !== 'number') return;
    wanted.set(key, id);
    flush();
    return () => {
      wanted.delete(key);
      flush();
    };
  });
}
