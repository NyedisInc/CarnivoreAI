
export interface RequiredEntry {
    readonly item_id: string;
    readonly required: boolean;
    readonly state: 'installed' | 'available' | 'declined' | 'blocked';
    readonly install_id: string | null;
    readonly local_edits: boolean | null;
}

/* is not installed */
export function shownEntries(entries: readonly RequiredEntry[]): RequiredEntry[] {
    return entries.filter((entry) => (entry.required && entry.state === 'blocked') || (entry.state === 'installed' && entry.local_edits === true));
}

export function offEntries(entries: readonly RequiredEntry[]): RequiredEntry[] {
    return entries.filter((entry) => entry.state === 'available' || entry.state === 'declined');
}

export function isFirstParty(itemId: string | undefined | null): boolean {
    return typeof itemId === 'string' && itemId.startsWith('carnivore/');
}
