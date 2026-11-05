import { whenLegacyBootComplete } from '../legacy-boot';
import { bridge, followPreference, savePreference } from '../zone-shell/preference-field';

export const ROW_LIGHTS_FIELD = 'row_lights_animate';

export const rowLights = $state({ on: true });

const animates = (value: unknown): boolean => value !== false;

let started = false;

export function refreshRowLights(): boolean {
    rowLights.on = animates(bridge()?.read(ROW_LIGHTS_FIELD, () => true));
    return rowLights.on;
}

export function startRowLights(target: Window | null = typeof window !== 'undefined' ? window : null): void {
    refreshRowLights();
    if (started) return;
    started = true;
    followPreference(ROW_LIGHTS_FIELD, animates, (on) => { rowLights.on = on; });
    whenLegacyBootComplete(target, refreshRowLights);
}

export async function saveRowLights(on: boolean): Promise<string | null> {
    const why = await savePreference(ROW_LIGHTS_FIELD, on);
    refreshRowLights();
    return why;
}
