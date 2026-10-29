import { authFetch } from '../../sdk';
import { BUILTIN_PACKS, readCharacterPack, type CharacterPack } from './characters';
import { adoptLook, type SwarmLook } from './characters/look-settings.svelte';
import { panelDensity, type PanelDensity } from './panel-state';
import type { HuddleDensity } from '../huddle-density';

export const PAGE_VIEWS = ['tree', 'org', 'squares'] as const;
export type PageView = (typeof PAGE_VIEWS)[number];

export const PANEL_DENSITIES = ['condensed', 'expanded', 'detailed'] as const;

export const UPPER_POSTURES = ['skip_all', 'ask'] as const;
export type UpperPosture = (typeof UPPER_POSTURES)[number];

export const FOLLOW_THEME = 'theme';

export const SWARM_DENSITY_KEY = 'cloude.huddle.swarmDensity';

export interface SwarmPageSettings {
  page_default_view: PageView;
  panel_default_density: PanelDensity;
  character_pack: string;
  upper_ranks_permissions: UpperPosture;
  closeout_window_minutes: number;
  max_children_per_parent: number | null;
  max_live_bodies: number | null;
  spawn_load_per_core: number | null;
  naming_family: boolean;
  chat_card_bodies: boolean;
}

export const OPTIONAL_LIMITS = [
  { key: 'max_children_per_parent', min: 1, max: 50, step: 1, whole: true },
  { key: 'max_live_bodies', min: 1, max: 200, step: 1, whole: true },
  { key: 'spawn_load_per_core', min: 0.25, max: 16, step: 0.25, whole: false },
] as const;
export type OptionalLimit = (typeof OPTIONAL_LIMITS)[number];

const DEFAULTS: SwarmPageSettings = {
  page_default_view: 'tree', panel_default_density: 'expanded', character_pack: FOLLOW_THEME, upper_ranks_permissions: 'skip_all',
  closeout_window_minutes: 15, max_children_per_parent: null, max_live_bodies: null, spawn_load_per_core: null, naming_family: false,
  chat_card_bodies: false,
};

export const swarmSettings = $state<SwarmPageSettings & { loaded: boolean }>({ ...DEFAULTS, loaded: false });

function loadDensity(): PanelDensity | null {
  try {
    const stored = globalThis.localStorage?.getItem(SWARM_DENSITY_KEY) ?? '';
    return (PANEL_DENSITIES as readonly string[]).includes(stored) ? (stored as PanelDensity) : null;
  } catch {
    return null;
  }
}

export const deviceDensity = $state<{ value: PanelDensity | null }>({ value: loadDensity() });

function adopt(answer: Partial<Record<keyof SwarmPageSettings, unknown>> | null | undefined): void {
  const view = answer?.page_default_view;
  const density = answer?.panel_default_density;
  const pack = answer?.character_pack;
  const upper = answer?.upper_ranks_permissions;
  const closeout = answer?.closeout_window_minutes;
  swarmSettings.page_default_view = (PAGE_VIEWS as readonly unknown[]).includes(view) ? (view as PageView) : DEFAULTS.page_default_view;
  swarmSettings.panel_default_density = (PANEL_DENSITIES as readonly unknown[]).includes(density) ? (density as PanelDensity) : DEFAULTS.panel_default_density;
  swarmSettings.character_pack = typeof pack === 'string' && pack !== '' ? pack : DEFAULTS.character_pack;
  swarmSettings.upper_ranks_permissions = (UPPER_POSTURES as readonly unknown[]).includes(upper) ? (upper as UpperPosture) : DEFAULTS.upper_ranks_permissions;
  swarmSettings.closeout_window_minutes = typeof closeout === 'number' && Number.isInteger(closeout) && closeout >= 1 ? closeout : DEFAULTS.closeout_window_minutes;
  swarmSettings.naming_family = answer?.naming_family === true;
  swarmSettings.chat_card_bodies = answer?.chat_card_bodies === true;
  for (const limit of OPTIONAL_LIMITS) {
    const value = answer?.[limit.key];
    swarmSettings[limit.key] = typeof value === 'number' && Number.isFinite(value) && value >= limit.min && value <= limit.max ? value : null;
  }
}

export type SwarmSettingsChange = Partial<SwarmPageSettings> & Partial<{ color_mode: SwarmLook['color_mode']; shapes: Partial<SwarmLook['shapes']>; animations: SwarmLook['animations'] }>;

export async function loadSwarmSettings(): Promise<void> {
  try {
    const answer = await authFetch<Partial<SwarmPageSettings> & Partial<SwarmLook>>('/swarm/settings');
    adopt(answer);
    adoptLook(answer);
  } catch (error) {
    console.debug('cplug.huddle: the swarm settings could not be read', error);
  } finally {
    swarmSettings.loaded = true;
  }
}

export async function saveSwarmSettings(changes: SwarmSettingsChange): Promise<boolean> {
  try {
    const answer = await authFetch<Partial<SwarmPageSettings> & Partial<SwarmLook>>('/swarm/settings', { method: 'PUT', body: JSON.stringify(changes) });
    adopt(answer);
    adoptLook(answer);
    return true;
  } catch (error) {
    console.debug('cplug.huddle: the swarm settings were not stored', error);
    return false;
  }
}

export function effectiveDensity(): PanelDensity {
  return deviceDensity.value ?? swarmSettings.panel_default_density;
}

export function setDeviceDensity(density: HuddleDensity): void {
  const value = panelDensity(density);
  deviceDensity.value = value;
  try {
    globalThis.localStorage?.setItem(SWARM_DENSITY_KEY, value);
  } catch {
  }
}

export function swarmChoices(): string[] {
  return [FOLLOW_THEME, ...Object.keys(BUILTIN_PACKS)];
}

export function activePack(): CharacterPack {
  const themes = (globalThis as unknown as { Themes?: { getActiveGlobal?: () => { characters?: unknown } | null } }).Themes;
  const override = swarmSettings.character_pack === FOLLOW_THEME ? null : swarmSettings.character_pack;
  return readCharacterPack(themes?.getActiveGlobal?.()?.characters ?? null, override);
}
