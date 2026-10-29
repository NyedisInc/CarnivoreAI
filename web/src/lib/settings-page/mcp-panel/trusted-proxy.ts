
export const MAX_TRUSTED_PROXIES = 8;

export type ProxyProblem = 'empty' | 'not_ip' | 'not_allowed' | 'duplicate' | 'full';
export type ProxyCheck = { ok: true; host: string } | { ok: false; problem: ProxyProblem };

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

export function canonicalIp(raw: string): string | null {
    const text = raw.trim();
    const v4 = IPV4.exec(text);
    if (v4) {
        const parts = v4.slice(1).map((p) => Number(p));
        return parts.every((p) => p <= 255) && v4.slice(1).every((p) => p === '0' || !p.startsWith('0')) ? parts.join('.') : null;
    }
    if (!text.includes(':') || !/^[0-9a-fA-F:.]+$/.test(text)) return null;
    let host: string;
    try {
        host = new URL(`http://[${text}]`).hostname.slice(1, -1);
    } catch {
        return null;
    }
    const mapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(host);
    if (mapped) {
        const hi = parseInt(mapped[1]!, 16);
        const lo = parseInt(mapped[2]!, 16);
        return `${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`;
    }
    return host;
}

function isReserved(ip: string): boolean {
    if (ip.includes(':')) return ip === '::' || ip === '::1' || /^ff/i.test(ip);
    const first = Number(ip.split('.')[0]);
    return first === 127 || first === 0 && ip === '0.0.0.0' || first >= 224 && first <= 239;
}

export function checkProxyEntry(raw: string, held: readonly string[]): ProxyCheck {
    if (!raw.trim()) return { ok: false, problem: 'empty' };
    const host = canonicalIp(raw);
    if (host === null) return { ok: false, problem: 'not_ip' };
    if (isReserved(host)) return { ok: false, problem: 'not_allowed' };
    if (held.some((h) => canonicalIp(h) === host)) return { ok: false, problem: 'duplicate' };
    if (held.length >= MAX_TRUSTED_PROXIES) return { ok: false, problem: 'full' };
    return { ok: true, host };
}
