
export interface CatalogAccountFacts {
    signedIn: boolean;
    handle: string;
    login: string | null;
    email?: string | null;
    provider: string | null;
}

export interface AccountIdentity {
    kind: 'member' | 'lurker';
    name: string;
    provider: string | null;
}

export function displayName(handle: string, login: string | null): string {
    const registered = handle.trim();
    if (registered) return registered;
    return (login ?? '').trim().split('@')[0] ?? '';
}

export function accountIdentity(facts: CatalogAccountFacts | null | undefined): AccountIdentity {
    const name = facts && facts.signedIn ? displayName(facts.handle, facts.login) : '';
    if (!name) return { kind: 'lurker', name: '', provider: null };
    return { kind: 'member', name, provider: facts?.provider ?? null };
}
