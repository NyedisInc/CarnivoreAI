import { authFetch } from '../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface Disclosure {
    report: string[];
    guest: string[];
}

export async function fetchDisclosure(fetcher: Fetcher = authFetch): Promise<Disclosure> {
    const body = await fetcher<Disclosure>('/catalog/install-report/disclosure');
    if (!body || !Array.isArray(body.report) || !Array.isArray(body.guest)) throw new Error('unexpected disclosure response');
    return body;
}
