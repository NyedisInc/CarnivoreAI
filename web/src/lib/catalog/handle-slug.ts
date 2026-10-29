export function suggestHandle(provider: string | null | undefined, login: string | null | undefined): string {
    const raw = (login ?? '').trim();
    if (!raw) return '';
    if (provider === 'github') return raw.toLowerCase();
    if (!raw.includes('@')) return '';
    const slug = raw.split('@')[0]!.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 39);
    return slug.length >= 3 ? slug : '';
}
