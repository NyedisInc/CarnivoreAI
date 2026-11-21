import { authFetch } from '../../opscenter/api/auth.svelte';
import type { CanBlock } from '../pack-machines/pack-machines-store.svelte';

export interface RescanAnswer {
  machine: string;
  toolchain: Record<string, boolean>;
  can: CanBlock | Record<string, never>;
  fresh: boolean;
}

export interface AbilitiesApi {
  rescan(machine: string): Promise<RescanAnswer>;
  putLabels(machine: string, labels: string[]): Promise<string[]>;
}

const base = (machine: string): string => `/pack/machines/${encodeURIComponent(machine)}`;

export const abilitiesApi: AbilitiesApi = {
  rescan: (machine) => authFetch<RescanAnswer>(`${base(machine)}/rescan`, { method: 'POST' }),
  putLabels: async (machine, labels) =>
    (await authFetch<{ machine: string; labels: string[] }>(`${base(machine)}/labels`, { method: 'PUT', body: JSON.stringify({ labels }) })).labels,
};
