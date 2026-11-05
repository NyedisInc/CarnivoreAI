import { whenLegacyBootComplete } from '../legacy-boot';
import { preferenceField } from '../preferences/field';

export const RAIL_DOCK_NAMES_FIELD = 'rail_dock_names';

const shows = (value: unknown): boolean => value !== false;

export const railDockNamesField = preferenceField<boolean>(RAIL_DOCK_NAMES_FIELD, shows, true);

export const railDockNames = $state({ on: true });

let started = false;

export function refreshRailDockNames(): boolean {
  railDockNames.on = railDockNamesField.read();
  return railDockNames.on;
}

export function startRailDockNames(target: Window | null = typeof window !== 'undefined' ? window : null): void {
  refreshRailDockNames();
  if (started) return;
  started = true;
  railDockNamesField.follow((on) => {
    railDockNames.on = on;
  });
  whenLegacyBootComplete(target, refreshRailDockNames);
}

export async function saveRailDockNames(on: boolean): Promise<string | null> {
  const why = await railDockNamesField.save(on);
  refreshRailDockNames();
  return why;
}
