import { openModal } from '../modal';
import type { Translate } from '../sessions/types';
import type { CardView } from './card';
import type { CatalogHost } from './catalog';
import OneShotPicker from './OneShotPicker.svelte';
import TrySheet from './TrySheet.svelte';
import { previewText } from './try-it';

export type TryResult = { kind: 'done' } | { kind: 'failed'; error: unknown };

export async function tryItem(a: { host: CatalogHost; t: Translate; card: CardView; name: string; files: number | null }): Promise<TryResult> {
    const { host, t, card, name, files } = a;
    const id = card.id || '';
    let body: string | null = null;
    try {
        body = await previewText(host, id);
    } catch (error) {
        return { kind: 'failed', error };
    }
    const shared = { name, body, host, t, writesInstructions: card.marksInstructionsWrite, instructionsDetails: card.instructionsDetails, instructionsMore: card.instructionsMore };
    const chosen = await openModal(TrySheet as never, { ...shared, files } as never);
    if (chosen === 'paste') await openModal(OneShotPicker as never, shared as never);
    return { kind: 'done' };
}
