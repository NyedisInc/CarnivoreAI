import { railBodyKey } from '../session-rail/rail-body-key';
import { ZONE_CELL_HEIGHT } from '../drawer-zone/zone-model';

export type BodyHost = 'rail' | 'drawer' | 'popout' | 'tab';

export interface HostLook {
  keyFor(cell: { id: string }, target: string | null, instance: string | null): string;
  surface: 'rail' | 'drawer' | null;
  zone: 'terminal' | 'drawer' | 'popout';
  page: 'terminal' | undefined;
  height: number | null;
  card: boolean;
  fitPlates: boolean;
  announceRemoved: boolean;
}

export const HOST_LOOKS: Readonly<Record<BodyHost, HostLook>> = {
  rail: {
    keyFor: railBodyKey,
    surface: 'rail',
    zone: 'terminal',
    page: 'terminal',
    height: null,
    card: false,
    fitPlates: true,
    announceRemoved: true,
  },
  drawer: {
    keyFor: (cell, target, instance) => `drawer-zone:${target ? `${cell.id}@${target}` : cell.id}${instance ? `#${instance}` : ''}`,
    surface: 'drawer',
    zone: 'drawer',
    page: undefined,
    height: ZONE_CELL_HEIGHT,
    card: true,
    fitPlates: true,
    announceRemoved: false,
  },
  tab: {
    keyFor: (cell) => `widget-tab:${cell.id}`,
    surface: null,
    zone: 'terminal',
    page: 'terminal',
    height: null,
    card: false,
    fitPlates: true,
    announceRemoved: false,
  },
  popout: {
    keyFor: (cell) => `popout-widget:${cell.id}`,
    surface: null,
    zone: 'popout',
    page: undefined,
    height: null,
    card: false,
    fitPlates: false,
    announceRemoved: false,
  },
};
