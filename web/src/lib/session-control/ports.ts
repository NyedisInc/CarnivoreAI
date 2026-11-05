import { openPage } from '../browser/select-push.svelte';

export interface PortLine {
    port: number;
    address: string;
    process: string | null;
    lan: boolean;
}

interface PortRecord { port: number; address?: string | null; process?: string | null }

export function isRemoteRow(row: Record<string, unknown> | null | undefined): boolean {
    if (!row) return false;
    const hostKey = row.host_key;
    if (typeof hostKey === 'string' && hostKey !== 'local') return true;
    const nested = row.session as { id?: unknown } | undefined;
    const id = typeof row.session_id === 'string' ? row.session_id : (typeof nested?.id === 'string' ? nested.id : '');
    return id.startsWith('remote:');
}

export function portLines(row: Record<string, unknown> | null | undefined): PortLine[] {
    const list = row && Array.isArray(row.local_servers) ? (row.local_servers as PortRecord[]) : [];
    return list
        .filter((s) => s && Number.isInteger(s.port))
        .sort((a, b) => a.port - b.port)
        .map((s) => {
            const address = s.address ?? 'localhost';
            return { port: s.port, address, process: s.process ?? null, lan: address === '0.0.0.0' || address === '::' };
        });
}

export async function openPort(port: number, where: 'here' | 'browser'): Promise<void> {
    const url = `http://localhost:${port}`;
    if (where === 'browser') {
        window.open(url, '_blank', 'noopener');
        return;
    }
    try {
        await openPage({ url });
    } catch (err) {
        console.warn('port open failed', port, err);
    }
}
