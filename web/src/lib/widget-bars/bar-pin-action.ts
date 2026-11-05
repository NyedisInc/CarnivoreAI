import { barLead } from './bar-lead.svelte';
import { widgetBars, type BarMode, type PinEdge } from './bar-settings.svelte';
import { phoneView } from '../drawer/phone-view.svelte';

let pinsOffered = true;

export function offerStripPins(on: boolean): void {
  pinsOffered = on;
}

export function stripPinsOffered(): boolean {
  return pinsOffered;
}

export function railPinOffered(): boolean {
  return pinsOffered && !phoneView();
}

export function barPinIconId(edge: PinEdge): string {
  return `pin:${edge}`;
}

export function stripMode(mode: BarMode): BarMode {
  return pinsOffered ? mode : 'autohide';
}

export function barPinned(edge: PinEdge): boolean {
  if (edge === 'rail' && pinsOffered && phoneView()) return true;
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
