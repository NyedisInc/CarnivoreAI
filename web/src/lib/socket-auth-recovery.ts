
export type SocketAuthOutcome = 'refreshed' | 'signed-out' | 'network-error';

export async function resolveAfterUnopenedClose(
    refresh: () => Promise<boolean>,
    isUnreachable: () => boolean,
): Promise<SocketAuthOutcome> {
    let ok: boolean;
    try {
        ok = await refresh();
    } catch {
        return 'network-error';
    }
    if (ok) return 'refreshed';
    return isUnreachable() ? 'network-error' : 'signed-out';
}
