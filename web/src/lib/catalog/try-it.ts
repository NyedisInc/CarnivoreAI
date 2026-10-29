import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
import type { Translate } from '../sessions/types';
import type { CatalogHost } from './catalog';
import { refusalCodeOf, refusalPayloadOf } from './install-actions';

export const OPENING_PROMPT_MAX_BYTES = 8192;

export const MAX_TASK_CHARS = 300;

function bodyText(preview: unknown): string | null {
    const body = (preview as { body?: unknown } | null | undefined)?.body;
    return typeof body === 'string' && body.trim() ? body : null;
}

export async function previewText(host: CatalogHost, itemId: string): Promise<string | null> {
    try {
        return bodyText(await host.previewInstall({ item_id: itemId, scope: 'global' }));
    } catch (error) {
        if (refusalCodeOf(error) === 'name_taken') {
            return bodyText(refusalPayloadOf(error));
        }
        throw error;
    }
}

export interface TryPrompt {
    prompt: string | null;
    tooLarge: boolean;
}

export function tryPrompt(body: string | null, task: string, t: Translate): TryPrompt {
    if (!body) return { prompt: null, tooLarge: false };
    const line = task.replace(/\s+/g, ' ').trim().slice(0, MAX_TASK_CHARS);
    const parts = [t(BROWSE_KEYS.tryPrefix), '', body.trimEnd()];
    if (line) parts.push('', t(BROWSE_KEYS.tryTaskLine, { task: line }));
    const prompt = parts.join('\n');
    if (new TextEncoder().encode(prompt).length > OPENING_PROMPT_MAX_BYTES) {
        return { prompt: null, tooLarge: true };
    }
    return { prompt, tooLarge: false };
}
