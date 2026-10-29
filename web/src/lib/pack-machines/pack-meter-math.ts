
export const METER_CELLS = 20;

export type MeterLevel = 'normal' | 'high' | 'critical';

export type LinkState = 'linked' | 'connecting' | 'down' | 'error';

export function filledCells(pct: number | null, cells: number = METER_CELLS): number {
  if (pct === null || !Number.isFinite(pct)) return 0;
  return Math.round((Math.min(100, Math.max(0, pct)) / 100) * cells);
}

export function reserveCells(reservePct: number | null | undefined, cells: number = METER_CELLS): number {
  return reservePct ? Math.round((Math.min(100, Math.max(0, reservePct)) / 100) * cells) : 0;
}

export function levelOf(pct: number | null): MeterLevel {
  if (pct !== null && pct >= 90) return 'critical';
  if (pct !== null && pct >= 75) return 'high';
  return 'normal';
}

export function loadPercent(load1: number | null | undefined, cores: number | null | undefined): number | null {
  if (load1 === null || load1 === undefined || !cores) return null;
  return Math.min(100, (load1 / cores) * 100);
}

export function linkStateOf(state: string): LinkState {
  if (state === 'connected') return 'linked';
  if (state === 'connecting' || state === 'waiting' || state === 'waiting_first_link') return 'connecting';
  if (state === 'refused' || state === 'error' || state === 'cert_mismatch') return 'error';
  return 'down';
}

export const PACK_STALE_SECONDS = 30;

export function linkMarkFor(m: { state: string; snapshot: unknown | null; age_seconds: number | null }): LinkState {
  if (m.state === 'connected' && (!m.snapshot || m.age_seconds === null || m.age_seconds > PACK_STALE_SECONDS)) return 'down';
  return linkStateOf(m.state);
}
