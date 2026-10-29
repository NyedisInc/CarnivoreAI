
import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { ThemeManifest } from '../../opscenter/api';
import { refusalMessage } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import { motionReduced } from '../motion/motion';

export const MAX_NOTE_CHARS = 1000;

export type Developer =
    | { kind: 'publisher'; handle: string; profileHandle: string | null; githubHref: string | null }
    | { kind: 'author'; text: string }
    | { kind: 'unset' };

const GITHUB_HANDLE_RE = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/;

export function developerOf(
    manifest: Pick<ThemeManifest, 'publisher' | 'author'> & { publisherGithub?: string | null },
): Developer {
    const handle = typeof manifest.publisher === 'string' ? manifest.publisher.trim() : '';
    if (handle) {
        const login = typeof manifest.publisherGithub === 'string' ? manifest.publisherGithub : '';
        return {
            kind: 'publisher',
            handle,
            profileHandle: GITHUB_HANDLE_RE.test(handle) ? handle : null,
            githubHref: GITHUB_HANDLE_RE.test(login) ? `https://github.com/${login}` : null,
        };
    }
    const author = typeof manifest.author === 'string' ? manifest.author.trim() : '';
    if (author) return { kind: 'author', text: author };
    return { kind: 'unset' };
}

export interface NoteSent {
    itemId: string | null;
    createdAt: string | null;
}

export async function sendNote(itemId: string, text: string): Promise<NoteSent> {
    const body = await authFetch<{ item_id?: string | null; created_at?: string | null }>(
        `/catalog/items/${encodeURIComponent(itemId)}/note`,
        { method: 'POST', body: JSON.stringify({ text }) },
    );
    return { itemId: body?.item_id ?? null, createdAt: body?.created_at ?? null };
}

export function reasonOfNoteFailure(error: unknown, t: Translate): string {
    if (error instanceof ApiError) {
        const payload = error.payload as { detail?: { code?: unknown } } | null | undefined;
        const nested = payload?.detail?.code;
        if (typeof nested === 'string' && nested.trim()) {
            return refusalMessage(nested.trim(), t);
        }
        return error.message;
    }
    if (error instanceof Error && error.message) return error.message;
    return t('error.server_unreachable');
}

export const RATINGS_SECTION_ID = 'tfb-ratings';

export function scrollToRatings(doc: Document = document): boolean {
    const el = doc.getElementById(RATINGS_SECTION_ID);
    if (!el) return false;
    const calm = motionReduced();
    el.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' });
    return true;
}
