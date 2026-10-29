import type { PanelState, ZoneVisibility } from './zone-types';

export interface VisibilityInput {
  unseen: boolean;
  panel: PanelState;
  active: boolean;
  docHidden: boolean;
  onScreen: boolean;
}

export function tabVisibility(i: VisibilityInput): ZoneVisibility {
  if (i.unseen || i.panel !== 'open') return 'parked';
  if (!i.active || i.docHidden || !i.onScreen) return 'hidden';
  return 'shown';
}

const RANK: Readonly<Record<ZoneVisibility, number>> = { shown: 0, hidden: 1, parked: 2 };

export function dimmest(...readings: (ZoneVisibility | undefined)[]): ZoneVisibility {
  return readings.reduce<ZoneVisibility>((worst, one) => (one && RANK[one] > RANK[worst] ? one : worst), 'shown');
}
