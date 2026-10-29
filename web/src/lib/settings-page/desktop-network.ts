
export type TlsLevel = 'secure' | 'insecure' | 'unknown';

export type BindKind = 'loopback' | 'all' | 'specific' | 'unknown';

export function bindKind(host: string | null | undefined): BindKind {
    const value = (host ?? '').trim().toLowerCase();
    if (!value) return 'unknown';
    if (value === 'localhost' || value === '::1' || value === '[::1]' || /^127(\.\d{1,3}){3}$/.test(value)) return 'loopback';
    if (value === '0.0.0.0' || value === '::' || value === '[::]' || value === '*') return 'all';
    return 'specific';
}

export function tlsKey(level: string | null | undefined, bind: BindKind): string {
    if (level === 'secure') return 'desktop.settings.tls.secure';
    if (level === 'insecure') return bind === 'loopback' ? 'desktop.settings.tls.local' : 'desktop.settings.tls.insecure';
    return 'desktop.settings.tls.unknown';
}
