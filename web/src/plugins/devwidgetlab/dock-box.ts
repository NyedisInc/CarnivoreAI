/* the panel itself */
import type { LabHost, LabSize } from '../sdk/widget-lab';
import { frameWidth } from './frame-url';
import { sizesToDraw } from './lab-model';
import type { Box } from './resize-model';
import type { DrawerDock } from './lab-selection';

export const DOCK_WINDOW: Readonly<Box> = Object.freeze({ w: 1280, h: 800 });
export const PANEL_EDGE_PX = 2;
export const BAR_PX = 36;
export const PANEL_DEFAULT_PX: Readonly<{ side: number; bottom: number }> = Object.freeze({ side: 380, bottom: 320 });

export function dockBox(host: string, dock: DrawerDock): Box | null {
  if (host !== 'drawer') return null;
  if (dock === 'right') return { w: PANEL_DEFAULT_PX.side - PANEL_EDGE_PX, h: DOCK_WINDOW.h };
  if (dock === 'bottom') return { w: DOCK_WINDOW.w - BAR_PX, h: PANEL_DEFAULT_PX.bottom - PANEL_EDGE_PX };
  return null;
}

export function dockEdge(dock: DrawerDock): 'side' | 'bottom' | null {
  return dock === 'right' ? 'side' : dock === 'bottom' ? 'bottom' : null;
}

export interface FrameBox {
  docked: Box | null;
  drawn: Box | null;
  base: Box | null;
  size: LabSize;
  mode: 'free' | 'w' | 'n' | 'none';
  /* the real left sidebar */
  spec: { box?: Box; dock?: 'side' | 'bottom'; shell?: 'sidebar' };
  sidebar: boolean;
}

export function frameBox(host: string, dock: DrawerDock, size: LabSize, custom: Box | null): FrameBox {
  const docked = dockBox(host, dock);
  const edge = dockEdge(dock);
  const sidebar = host === 'drawer' && dock === 'left';
  const drawn = host === 'drawer' && !docked ? null : (custom ?? docked);
  const base = docked ?? (size.h !== null ? { w: size.w, h: size.h } : null);
  return {
    docked, drawn, base,
    size: drawn ? { ...size, w: drawn.w, h: drawn.h } : size,
    mode: docked ? (dock === 'right' ? 'w' : 'n') : host === 'drawer' ? 'none' : 'free',
    spec: { ...(drawn ? { box: drawn } : {}), ...(docked && edge ? { dock: edge } : {}), ...(sidebar ? { shell: 'sidebar' as const } : {}) },
    sidebar,
  };
}

export function settledBox(next: Box, base: Box | null): Box | null {
  return base && next.w === base.w && next.h === base.h ? null : next;
}

export function sizesOnShow(host: LabHost, picked: readonly string[], dock: DrawerDock): LabSize[] {
  const sizes = sizesToDraw(host, picked);
  return dockBox(host.zone, dock) ? sizes.slice(0, 1) : sizes;
}

export function drawnWidth(host: string, dock: DrawerDock, size: LabSize): number {
  return frameWidth(size, dockBox(host, dock)?.w);
}
