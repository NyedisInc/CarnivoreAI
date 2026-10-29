import { openModal } from '../modal';
import type { Translate } from '../sessions/types';
import type { CardView } from './card';
import type { CatalogHost } from './catalog';
import ConfirmSheet from './ConfirmSheet.svelte';
import { refusalCodeOf } from './install-actions';
import { consentTextOf, ledgerFailure, revisionOf, updateConsentSheet, updateSheet } from './installed-actions';
import type { InstalledItem, UpdateConsent } from './types';

export type LedgerOutcome = ReturnType<typeof ledgerFailure>;

export type UpdateResult =
    | { kind: 'updated'; row: InstalledItem }
    | { kind: 'cancelled' }
    | { kind: 'failed'; outcome: LedgerOutcome };

export interface UpdateContext {
    host: CatalogHost;
    t: Translate;
    name: string;
    card: CardView;
    installed: InstalledItem | null;
}

export async function acceptNewText(
    ctx: UpdateContext,
    revision: number,
    error: unknown,
    send: (body: { expected_revision: number; consent: UpdateConsent }) => Promise<InstalledItem>,
): Promise<UpdateResult> {
    const { host, t, name, card, installed } = ctx;
    const { body: text, sha, digest, scripts, diff, requiresConsent, cplugFacts } = consentTextOf(error);
    const agreed = await openModal(ConfirmSheet as never, updateConsentSheet(name, text, scripts, t, diff, card.isCplug ? cplugFacts : undefined) as never);
    if (!agreed || !sha) return { kind: 'failed', outcome: { kind: 'refused', code: 'consent_required' } };
    try {
        const consent: UpdateConsent = { body_sha: sha };
        if (digest) consent.digest = digest;
        if (requiresConsent || scripts.length) consent.scripts = true;
        return { kind: 'updated', row: await send({ expected_revision: revision, consent }) };
    } catch (retryError) {
        return { kind: 'failed', outcome: ledgerFailure(retryError) };
    }
}

export async function runUpdate(ctx: UpdateContext, onAgreed?: () => void): Promise<UpdateResult> {
    const { host, t, name, card, installed } = ctx;
    const revision = revisionOf(installed);
    const installId = installed && installed.install_id;
    if (!installId || revision === null) return { kind: 'cancelled' };
    const agreed = await openModal(
        ConfirmSheet as never,
        updateSheet(name, installed?.version ?? null, card.version ?? null, t, card.marksInstructionsWrite ? card.instructionsDetails : null, card.instructionsMore) as never,
    );
    if (!agreed) return { kind: 'cancelled' };
    onAgreed?.();
    try {
        return { kind: 'updated', row: await host.applyUpdate(installId, { expected_revision: revision }) };
    } catch (error) {
        if (refusalCodeOf(error) === 'consent_required') return acceptNewText(ctx, revision, error, (sent) => host.applyUpdate(installId, sent));
        return { kind: 'failed', outcome: ledgerFailure(error) };
    }
}
