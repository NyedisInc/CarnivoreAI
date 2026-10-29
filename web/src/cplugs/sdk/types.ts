import type { DynamicTabDef } from '../../lib/dynamic-tabs/types';
import type { RailItem } from '../../opscenter/shell/rail-items';
import type { Contribution } from '../../lib/plugins/types';
import type { Component } from 'svelte';
import type { CellMeta } from '../../opscenter/engine/types';
import type { CoreExtras } from '../../opscenter/widgets/core-manifests';

/* the whole file */
export interface CplugManifest {
  schema: number;
  id: string;
  name_key: string;
  description_key: string;
  version: string;
  icon: string;
  tier: 'core' | 'builtin' | 'dev' | string;
  default_enabled?: boolean;
  permissions?: { app?: string[] };
  surfaces: {
    tabs?: string[]; menu_links?: string[]; plugins?: string[]; widgets?: string[]; topics?: string[];
    page_section?: string; page_section_label_key?: string; page_section_icon?: string;
  };
  widgets?: Record<string, { instancing: 'singleton' | 'per-target'; fits: { sizes: string[]; anySize?: boolean; max_per_surface?: number } }>;
  css_prefix?: string;
  owns?: { routes?: string[]; strings?: string[]; styles?: string[]; assets?: string[]; tests?: string[]; migrations?: string[]; style_guide?: string[]; contributions?: string[]; files?: string[] };
  requires?: string[];
}

export interface CplugWidget {
  name: string;
  meta: CellMeta;
  component: Component<any>;
  extras: CoreExtras;
}

export interface CplugWeb {
  id: string;
  manifest: CplugManifest;
  tabs?: DynamicTabDef[];
  plugins?: Contribution[];
  menuLinks?: RailItem[];
  widgets?: CplugWidget[];
  accountMenuItems?: AccountMenuItem[];
  /* the bottom bar */
  barIndicators?: BarIndicator[];
  start?: () => void;
}

export interface AccountMenuRun {
  close(): void;
  anchor: HTMLElement | null;
}

export interface AccountMenuItem {
  id: string;
  icon: string;
  label(): string;
  checked?(): boolean;
  visible?(): boolean;
  run(ctx: AccountMenuRun): void;
}

export interface BarIndicator {
  id: string;
  icon: string;
  visible(): boolean;
  label(): string;
  tone?(): 'lit' | 'quiet';
  run(anchor: HTMLElement | null): void;
}

export interface CplugPopout {
  id: string;
  manifest: CplugManifest;
  tabs: DynamicTabDef[];
  widgets?: CplugWidget[];
}

export interface PluginSpecimen {
  id: string;
  component: Component<Record<string, unknown>>;
  props?: Record<string, unknown>;
}
