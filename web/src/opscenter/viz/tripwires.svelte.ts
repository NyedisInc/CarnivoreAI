import { authFetch } from '../api/auth.svelte';
import type { Tripwire, TripwireWrite } from './tripwire-model';

export const tripwires = $state<{ list: Tripwire[] }>({ list: [] });

export async function loadTripwires(): Promise<void> {
  try {
    tripwires.list = await authFetch<Tripwire[]>('/stats/tripwires');
  } catch {
  }
}

export async function saveTripwire(id: string | null, body: TripwireWrite): Promise<Tripwire> {
  const saved = await authFetch<Tripwire>(id ? `/stats/tripwires/${encodeURIComponent(id)}` : '/stats/tripwires', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
  tripwires.list = id ? tripwires.list.map((wire) => wire.id === id ? saved : wire) : [...tripwires.list, saved];
  return saved;
}

export async function removeTripwire(id: string): Promise<void> {
  await authFetch<void>(`/stats/tripwires/${encodeURIComponent(id)}`, { method: 'DELETE' });
  tripwires.list = tripwires.list.filter((wire) => wire.id !== id);
}
