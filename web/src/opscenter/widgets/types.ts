
import type { LayoutPage } from '../engine/types';
import type { GridSizeName } from './named-sizes';

export type WidgetCanvas = LayoutPage;

export const WIDGET_CANVASES: readonly WidgetCanvas[] = ['home', 'terminal'];

export type WidgetLook = 'compact' | 'full';

export const WIDGET_LOOKS: readonly WidgetLook[] = ['compact', 'full'];

export const LOOK_SURFACES: readonly string[] = ['home', 'drawer'];

export interface WidgetLooks {
  names: readonly WidgetLook[];
  defaults: Readonly<Partial<Record<'home' | 'drawer', WidgetLook>>>;
}

/*  hidden  */
export type WidgetInstancing = 'singleton' | 'per-target';

export const WIDGET_INSTANCINGS: readonly WidgetInstancing[] = ['singleton', 'per-target'];

export type WidgetCategory = 'overview' | 'sessions' | 'catalog' | 'monitoring' | 'tools' | 'live' | 'plugins';

export const WIDGET_CATEGORIES: readonly WidgetCategory[] = [
  'overview',
  'sessions',
  'catalog',
  'monitoring',
  'tools',
  'live',
  'plugins',
];

export type WidgetType = 'kpi' | 'list' | 'monitor' | 'feed' | 'tool' | 'pane' | 'chart' | 'plugin';

export const WIDGET_TYPES: readonly WidgetType[] = ['kpi', 'list', 'monitor', 'feed', 'tool', 'pane', 'chart', 'plugin'];

export type WidgetCapability = 'navigate' | 'session-control' | 'server-write' | 'terminal-input' | 'browser-control';

export const WIDGET_CAPABILITIES: readonly WidgetCapability[] = [
  'navigate',
  'session-control',
  'server-write',
  'terminal-input',
  'browser-control',
];

export interface DensityTier {
  name: string;
  min: number;
}

export interface DensityLadders {
  width: readonly DensityTier[];
  height: readonly DensityTier[];
}

export interface WidgetDensity {
  width: string;
  height: string;
}

export interface WidgetBounds {
  minW: number;
  minH: number;
  maxW?: number;
  maxH?: number;
}

export type FitZone = 'home' | 'terminal' | 'drawer' | 'popout';

export interface FitSize {
  w: number;
  h: number;
}

export interface WidgetFits {
  min: FitSize;
  sizes: readonly GridSizeName[];
  anySize: boolean;
  max_per_surface?: number;
}

export const MAX_PER_SURFACE_CEILING = 12;

export interface BooleanSettingField {
  kind: 'boolean';
  labelKey: string;
  hintKey?: string;
  keywordsKey?: string;
  default: boolean;
  /* cannot be changed */
  disabledWhen?: string;
}

export interface NumberSettingField {
  kind: 'number';
  labelKey: string;
  hintKey?: string;
  keywordsKey?: string;
  default: number;
  min?: number;
  max?: number;
}

export interface EnumSettingField {
  kind: 'enum';
  labelKey: string;
  hintKey?: string;
  keywordsKey?: string;
  options: readonly string[];
  default: string;
  control?: 'segmented' | 'select';
}

export interface StringSettingField {
  kind: 'string';
  labelKey: string;
  hintKey?: string;
  keywordsKey?: string;
  default: string;
  maxLength: number;
}

export type WidgetSettingField = BooleanSettingField | NumberSettingField | EnumSettingField | StringSettingField;

export interface WidgetSettingsSchema {
  version: number;
  fields: Readonly<Record<string, WidgetSettingField>>;
  /* the settings overlay */
  groups?: readonly WidgetSettingsGroup[];
}

/* the settings overlay */
export interface WidgetSettingsGroup {
  labelKey: string;
  fields: readonly string[];
  matrix?: SettingsMatrix;
}

export interface SettingsMatrix {
  columns: readonly string[];
  rows: readonly SettingsMatrixRow[];
}

export interface SettingsMatrixRow {
  labelKey: string;
  hintKey?: string;
  fields?: readonly string[];
  confirm?: Readonly<Record<string, string>>;
  locked?: true;
}

export interface WidgetManifest {
  id: string;
  version: string;
  titleKey: string;
  icon: string;
  iconTone: string;
  category: WidgetCategory;
  type: WidgetType;
  instancing: WidgetInstancing;
  canvases: readonly WidgetCanvas[];
  looks?: WidgetLooks;
  bounds: WidgetBounds;
  fits: WidgetFits;
  densities: DensityLadders;
  settings?: WidgetSettingsSchema;
  capabilities: readonly WidgetCapability[];
  keepAlive?: 'host';
  scope?: WidgetScope;
  views?: readonly WidgetView[];
  viewOf?: string;
  remembers?: readonly string[];
}

export interface WidgetView {
  id: string;
  titleKey: string;
  widget: string;
}

export type WidgetScope = 'session';

export type ManifestRefusal =
  | 'not-an-object'
  | 'unknown-field'
  | 'id'
  | 'version'
  | 'title-key'
  | 'icon'
  | 'icon-tone'
  | 'category'
  | 'type'
  | 'instancing'
  | 'canvases'
  | 'looks'
  | 'bounds'
  | 'fits'
  | 'densities'
  | 'settings'
  | 'capabilities'
  | 'keep-alive'
  | 'scope'
  | 'views'
  | 'view-of'
  | 'remembers';

export type ManifestCheck =
  | { ok: true; manifest: WidgetManifest }
  | { ok: false; refusal: ManifestRefusal; detail: string };
