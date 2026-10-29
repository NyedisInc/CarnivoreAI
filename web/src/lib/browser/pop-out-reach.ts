
export type RealPageRefusal = 'no_address' | 'host_only';

export type RealPageReach = { ok: true; url: string } | { ok: false; reason: RealPageRefusal };

const IPV4_LOOPBACK = /^127(?:\.\d{1,3}){3}$/;

export function isLoopbackHost(host: string): boolean {
    const h = host.trim().toLowerCase().replace(/\.$/, '');
    return h === 'localhost' || h.endsWith('.localhost') || IPV4_LOOPBACK.test(h) || h === '[::1]' || h === '::1'
        || h === '0.0.0.0';
}

export function realPageReach(url: string | null | undefined, viewerHost: string): RealPageReach {
    let parsed: URL;
    try {
        parsed = new URL(url ?? '');
    } catch {
        return { ok: false, reason: 'no_address' };
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return { ok: false, reason: 'no_address' };
    if (isLoopbackHost(parsed.hostname) && !isLoopbackHost(viewerHost)) return { ok: false, reason: 'host_only' };
    return { ok: true, url: parsed.href };
}
