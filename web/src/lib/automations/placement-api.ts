import { authFetch } from '../../opscenter/api/auth.svelte';

export type Placement = 'here' | 'auto';

export interface PlacementAnswer {
  placement: Placement;
  applies: boolean;
}

export interface PlacementApi {
  read(automationId: string): Promise<PlacementAnswer>;
  write(automationId: string, placement: Placement): Promise<PlacementAnswer>;
}

const url = (id: string): string => `/automations/${encodeURIComponent(id)}/placement`;

export const placementApi: PlacementApi = {
  read: (id) => authFetch<PlacementAnswer>(url(id)),
  write: (id, placement) => authFetch<PlacementAnswer>(url(id), { method: 'PUT', body: JSON.stringify({ placement }) }),
};
