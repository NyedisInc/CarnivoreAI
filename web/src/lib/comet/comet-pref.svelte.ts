import { whenLegacyBootComplete } from '../legacy-boot';
import { bridge, followPreference, savePreference } from '../zone-shell/preference-field';

export const COMET_ON_FIELD = 'comet_on';
export const COMET_LAP_FIELD = 'comet_lap_seconds';
export const COMET_COLOR_FIELD = 'comet_unread_color';

export const COMET_LAP_MIN = 0.5;
export const COMET_LAP_MAX = 30;
export const COMET_LAP_DEFAULT = 3;

export const COMET_COLORS = ['celestial', 'green', 'accent'] as const;
export type CometColor = (typeof COMET_COLORS)[number];

export const comet = $state<{ on: boolean; lap: number; color: CometColor }>({ on: true, lap: COMET_LAP_DEFAULT, color: 'celestial' });

const asOn = (value: unknown): boolean => value !== false;
const asLap = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) && value >= COMET_LAP_MIN && value <= COMET_LAP_MAX ? value : COMET_LAP_DEFAULT;
const asColor = (value: unknown): CometColor => ((COMET_COLORS as readonly unknown[]).includes(value) ? (value as CometColor) : 'celestial');

export function lapInRange(value: number): boolean {
  return Number.isFinite(value) && value >= COMET_LAP_MIN && value <= COMET_LAP_MAX;
}

function paint(): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.style.setProperty('--oc-comet-lap', `${comet.lap}s`);
  root.setAttribute('data-comet-color', comet.color);
}

export function refreshComet(): void {
  const b = bridge();
  comet.on = asOn(b?.read(COMET_ON_FIELD, () => true));
  comet.lap = asLap(b?.read(COMET_LAP_FIELD, () => COMET_LAP_DEFAULT));
  comet.color = asColor(b?.read(COMET_COLOR_FIELD, () => 'celestial'));
  paint();
}

let started = false;

export function startComet(target: Window | null = typeof window !== 'undefined' ? window : null): void {
  refreshComet();
  if (started) return;
  started = true;
  followPreference(COMET_ON_FIELD, asOn, (on) => { comet.on = on; });
  followPreference(COMET_LAP_FIELD, asLap, (lap) => { comet.lap = lap; paint(); });
  followPreference(COMET_COLOR_FIELD, asColor, (color) => { comet.color = color; paint(); });
  whenLegacyBootComplete(target, refreshComet);
}

export async function saveComet(field: string, value: boolean | number | string): Promise<string | null> {
  const why = await savePreference(field, value);
  refreshComet();
  return why;
}
