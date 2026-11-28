import { authFetch } from '../../opscenter/api/auth.svelte';

export interface Leftover {
  install_id: string;
  name: string;
  newest_at: number | null;
  rows: Record<string, number>;
}

export interface Leftovers {
  known: boolean;
  leftovers: Leftover[];
}

export const readLeftovers = (): Promise<Leftovers> => authFetch<Leftovers>('/pack/leftovers');

export const forgetLeftover = (installId: string): Promise<unknown> =>
  authFetch(`/pack/leftovers/${encodeURIComponent(installId)}`, { method: 'DELETE' });

export const rowCount = (item: Pick<Leftover, 'rows'>): number => Object.values(item.rows ?? {}).reduce((a, b) => a + b, 0);
