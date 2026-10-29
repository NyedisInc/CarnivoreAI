import { barLead } from './bar-lead.svelte';
import { widgetBars, type BarMode, type PinEdge } from './bar-settings.svelte';

let pinsOffered = true;

export function offerStripPins(on: boolean): void {
  pinsOffered = on;
}

export function stripPinsOffered(): boolean {
  return pinsOffered;
}

export function stripMode(mode: BarMode): BarMode {
  return pinsOffered ? mode : 'autohide';
}

export function barPinned(edge: PinEdge): boolean {
  return stripMode((edge === 'rail' ? widgetBars.rail : widgetBars.view[edge]).mode) === 'pinned';
}

export async function toggleBarPin(edge: PinEdge): Promise<void> {
  if (edge === 'rail') {
    await widgetBars.setRail(barPinned('rail') ? 'autohide' : 'pinned');
    return;
  }
  const pinned = barPinned(edge);
  if (!pinned) barLead.take(edge);
  await widgetBars.set(edge, { mode: pinned ? 'autohide' : 'pinned' });
}
