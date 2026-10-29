import type { ResolvedPlacement } from '../../opscenter/widgets/placement-resolve';
import type { PlacementOptions } from '../../opscenter/widgets/placement-options';
import type { FrameHeader } from '../../opscenter/shell/frame-header.svelte';
import type { MenuHost } from './placement-menu';
import type { PlacementSource } from './source';
import type { WidgetManifest } from '../../opscenter/widgets/types';

export type TabKind = 'terminal' | 'page' | 'widget' | 'panel';

export type ZoneVisibility = 'shown' | 'hidden' | 'parked';

export type PanelState = 'open' | 'collapsed' | 'closed';

export interface TabRef {
  key: string;
  kind: TabKind;
  placement?: ResolvedPlacement;
  source?: PlacementSource | null;
  options?: PlacementOptions;
  unseen?: boolean;
}

export type ZoneToolbarPlace = 'header' | 'strip' | 'corner' | 'none';

export type ZoneMenuAnchor = HTMLElement | { x: number; y: number; anchor?: HTMLElement };

export interface ZoneSpec {
  key: string;
  tabs: () => readonly TabRef[];
  active: () => string | null;
  select: (key: string) => void;
  panel: () => PanelState;
  strip: 'tabs' | 'keys' | 'none';
  toolbar: ZoneToolbarPlace;
  menuHost: MenuHost;
  headerId?: (tab: TabRef) => string;
  openMenu?: (tab: TabRef, anchor: ZoneMenuAnchor) => boolean | void;
  seedHeader?: (header: FrameHeader) => void;
}

export interface KeyFace {
  title: string;
  ariaLabel: string;
  tip: string;
  label: string;
  icon: string;
  badge?: WidgetManifest;
  count?: number | null;
  options?: PlacementOptions;
  chip: boolean;
  letter: string;
  tone: string;
  global?: boolean;
}

export type TabKeyShape = 'icon' | 'tab' | 'tile';

export type TabKeyVariant = 'bar' | 'rail' | 'strip' | 'mini' | 'topbar' | 'phone' | 'glance';

export interface TabKeyClose {
  label: string;
  run: (event: MouseEvent) => void;
  armed?: boolean;
  attrs?: Record<string, string | number | boolean | undefined>;
  onpress?: (event: PointerEvent) => void;
  onrelease?: () => void;
}

export type TabKeyState = 'expanded' | 'pressed' | 'selected';
