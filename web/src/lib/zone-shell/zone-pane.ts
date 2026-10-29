import { getContext, setContext } from 'svelte';
import type { FrameHeader } from '../../opscenter/shell/frame-header.svelte';
import type { TabRef, ZoneVisibility } from './zone-types';

const ZONE_PANE = Symbol('zone-pane');

export interface ZonePaneContext {
  readonly tab: TabRef;
  readonly header: FrameHeader;
  readonly visible: ZoneVisibility;
}

export function provideZonePane(pane: ZonePaneContext): void {
  setContext(ZONE_PANE, pane);
}

export function useZonePane(): ZonePaneContext | undefined {
  return getContext<ZonePaneContext | undefined>(ZONE_PANE);
}
