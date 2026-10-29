
/* (anything with a */
export function countByDisplayKind(items: readonly { kind?: string | null }[], kinds: readonly string[]): Record<string, number> {
    return Object.fromEntries(kinds.map((kind) => [kind, items.filter((item) => displayKind(item.kind) === kind).length]));
}

const INDEX_KIND_CPLUG = 'cplug';
const DISPLAY_KIND: Readonly<Record<string, string>> = { [INDEX_KIND_CPLUG]: 'plugin' };

export function displayKind(kind: string | null | undefined): string | null {
    if (!kind) return null;
    return Object.hasOwn(DISPLAY_KIND, kind) ? (DISPLAY_KIND[kind] ?? kind) : kind;
}

export function isCplugIndexKind(kind: string | null | undefined): boolean {
    return kind === INDEX_KIND_CPLUG;
}
