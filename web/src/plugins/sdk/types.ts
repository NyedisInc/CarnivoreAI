import type { DynamicTabDef } from '../../lib/dynamic-tabs/types';
import type { RailItem } from '../../opscenter/shell/rail-items';
import type { Contribution } from '../../lib/plugins/types';
import type { Component } from 'svelte';
import type { CellMeta } from '../../opscenter/engine/types';
import type { CoreExtras } from '../../opscenter/widgets/core-manifests';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { PluginCellId } from '../../opscenter/cells/registry';

export interface CplugManifest {
  schema: number;
  id: string;
  name_key?: string;
  description_key?: string;
  name?: string;
  description?: string;
  kind?: string;
  version: string;
  icon?: string;
  tier: 'core' | 'builtin' | 'dev' | 'catalog' | 'local' | string;
  default_enabled?: boolean;
  permissions?: {
    app?: string[];
    read?: string[];
    write?: string[];
    network?: unknown[];
    lan?: unknown[];
    secrets?: unknown[];
    services?: string[];
    events?: string[];
    reasons?: Record<string, string>;
  };
  surfaces?: {
    tabs?: string[]; menu_links?: string[]; plugins?: string[]; widgets?: string[]; topics?: string[];
    page_section?: string; page_section_label_key?: string; page_section_icon?: string;
  };
  ui?: {
    routes?: boolean | string[];
    tabs?: string[]; menu_links?: string[]; plugins?: string[]; widgets?: string[]; topics?: string[];
    page_section?: string; page_section_label_key?: string; page_section_icon?: string;
    popout?: boolean | { enabled?: boolean; multi?: boolean; width?: number; height?: number } | Record<string, unknown>;
    contribute?: Record<string, unknown[]>;
    [key: string]: unknown;
  };
  mcp?: {
    tools?: string[] | unknown[];
  };
  settings_schema?: WidgetSettingsSchema;
  ui_contribute?: Record<string, unknown[]>;
  services?: {
    provides?: Array<{ name: string; methods: string[]; schemas?: Record<string, unknown> }>;
    consumes?: string[];
  };
  events?: {
    on?: string[];
    emit?: string[];
  };
  webhooks?: Record<string, { hmac_secret: string; header?: string }>;
  widgets?: Record<string, { instancing: 'singleton' | 'per-target'; fits: { sizes: string[]; anySize?: boolean; max_per_surface?: number } }>;
  css_prefix?: string;
  owns?: { routes?: string[]; strings?: string[]; styles?: string[]; assets?: string[]; tests?: string[]; migrations?: string[]; style_guide?: string[]; contributions?: string[]; files?: string[] };
  requires?: string[];
  renamed_from?: string;
  renamed_from_keeps?: string[];
}

export interface CplugWidget {
  name: string;
  meta: CellMeta;
  component: Component<any>;
  extras: CoreExtras;
}

export interface CplugCell {
  id: PluginCellId;
  component: CplugWidget['component'];
}

export interface CplugWeb {
  id: string;
  manifest: CplugManifest;
  tabs?: DynamicTabDef[];
  plugins?: Contribution[];
  menuLinks?: RailItem[];
  widgets?: CplugWidget[];
  cells?: CplugCell[];
  accountMenuItems?: AccountMenuItem[];
  barIndicators?: BarIndicator[];
  start?: () => void;
  stop?: () => void;
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
  cells?: CplugCell[];
  start?: () => void;
}

export interface PluginSpecimen {
  id: string;
  component: Component<Record<string, unknown>>;
  props?: Record<string, unknown>;
}
