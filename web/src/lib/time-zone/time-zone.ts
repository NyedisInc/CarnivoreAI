
import { bridge, followPreference, savePreference } from '../zone-shell/preference-field';

export const TIME_ZONE_FIELD = 'time_zone';

export const DEFAULT_TIME_ZONE = 'America/New_York';

export function asZone(value: unknown): string {
    return typeof value === 'string' && value ? value : DEFAULT_TIME_ZONE;
}

export function supportedZones(): string[] {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    let names: string[] = [];
    try {
        names = intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : [];
    } catch {
        names = [];
    }
    return Array.from(new Set([...names, 'UTC', DEFAULT_TIME_ZONE])).sort();
}

export function filterZones(zones: readonly string[], query: string): string[] {
    const words = query.toLowerCase().split(/[\s_/]+/).filter(Boolean);
    if (!words.length) return [...zones];
    return zones.filter((zone) => {
        const flat = zone.toLowerCase().replace(/_/g, ' ');
        return words.every((word) => flat.includes(word));
    });
}

export function readTimeZone(): string {
    return asZone(bridge()?.read(TIME_ZONE_FIELD, () => null));
}

export function saveTimeZone(zone: string): Promise<string | null> {
    return savePreference(TIME_ZONE_FIELD, zone);
}

export function followTimeZone(apply: (zone: string) => void): () => void {
    return followPreference(TIME_ZONE_FIELD, asZone, apply);
}
