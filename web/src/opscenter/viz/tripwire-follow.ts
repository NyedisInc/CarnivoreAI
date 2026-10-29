import { subscribe } from '../api/events.svelte';
import type { EventFrame } from '../api/types';
import { applyFrame, type TripwireFrame } from './tripwire-model';
import { loadTripwires, tripwires } from './tripwires.svelte';

let following = false;

export function followTripwires(): void {
  if (following) return;
  following = true;
  subscribe('stats.tripwire', (frame: EventFrame) => { tripwires.list = applyFrame(tripwires.list, frame as unknown as TripwireFrame); });
  subscribe('events.hello', () => { void loadTripwires(); });
  void loadTripwires();
}
