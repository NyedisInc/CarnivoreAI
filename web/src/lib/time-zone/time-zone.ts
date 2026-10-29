
export const TIME_ZONE_FIELD = 'time_zone';

export const DEFAULT_TIME_ZONE = 'America/New_York';

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

const SAVED = new Set(['committed', 'unchanged']);

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

export async function saveTimeZone(zone: string): Promise<string | null> {
    const found = bridge();
    if (!found) return 'unavailable';
    const result = (await found.write(TIME_ZONE_FIELD, zone, () => {})) as { status?: string; detail?: string } | null;
    const status = result && typeof result.status === 'string' ? result.status : '';
    if (SAVED.has(status)) return null;
    return (result && result.detail) || status || 'the server did not answer';
}

export function followTimeZone(apply: (zone: string) => void): () => void {
    const found = bridge();
    if (!found || typeof found.follow !== 'function') return () => {};
    return found.follow(TIME_ZONE_FIELD, (value) => apply(asZone(value)));
}
