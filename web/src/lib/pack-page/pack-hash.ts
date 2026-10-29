
export const PACK_TABS = ['computers', 'work', 'logins', 'skills'] as const;

export type PackTab = (typeof PACK_TABS)[number];

const OLD_TAB: Record<string, PackTab> = { machines: 'computers', pack: 'computers', ssh: 'computers' };

const SSH_SLUGS: readonly string[] = ['ssh', 'machines'];

const ADDRESS = /^#?(?:settings\/)?(?:hosts|pack)(?:\/([a-z_]+))?$/;

export function packTabOf(hash: string | null | undefined): { tab: PackTab | null; ssh: boolean } | null {
    if (typeof hash !== 'string') return null;
    if (hash.trim() === '#ssh') return { tab: 'computers', ssh: true };
    const match = ADDRESS.exec(hash.trim());
    if (!match) return null;
    const slug = match[1] ?? null;
    const tab = slug === null ? null : (PACK_TABS as readonly string[]).includes(slug) ? (slug as PackTab) : (OLD_TAB[slug] ?? null);
    return { tab, ssh: slug !== null && SSH_SLUGS.includes(slug) };
}

export function packFragment(tab?: PackTab | null): string {
    return tab ? `#pack/${tab}` : '#pack';
}
