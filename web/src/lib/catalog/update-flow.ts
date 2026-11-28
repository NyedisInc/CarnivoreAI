import { openModal } from '../modal';
import type { Translate } from '../sessions/types';
import type { CardView } from './card';
import type { CatalogHost } from './catalog';
import ConfirmSheet from './ConfirmSheet.svelte';
import { refusalCodeOf, refusalPayloadOf } from './install-actions';
import { consentTextOf, ledgerFailure, revisionOf, updateConsentSheet, updateSheet } from './installed-actions';
import { flaggedMetaFromSheet, isProvenanceBlocked, permissionDiffFromError } from './permission-diff';
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

export type CarriedUpdateConsent = Partial<UpdateConsent> & {
    readonly accept_permission_escalation?: boolean;
    readonly cplug_flagged_ack?: boolean;
    readonly acknowledge_flagged?: boolean;
};

export async function acceptNewText(
    ctx: UpdateContext,
    revision: number,
    error: unknown,
    send: (body: { expected_revision: number; consent: UpdateConsent }) => Promise<InstalledItem>,
    carried?: CarriedUpdateConsent,
): Promise<UpdateResult> {
    const { t, name, card } = ctx;
    const code = refusalCodeOf(error);
    const {
        body: text,
        sha,
        digest,
        scripts,
        diff,
        requiresConsent,
        cplugFacts,
        releaseNotes,
    } = consentTextOf(error);
    const permissionDiff = permissionDiffFromError(error);
    const flaggedMeta = flaggedMetaFromSheet(
        refusalPayloadOf(error),
        code === 'cplug_flagged_ack_required' ? { flagged: true } : undefined,
    );
    const flaggedWarning = flaggedMeta.flagged || flaggedMeta.requiresWarningAck ? flaggedMeta : null;
    const blocked = isProvenanceBlocked(permissionDiff) || code === 'commit_sha_mismatch';
    const passedFacts = card.isCplug && (cplugFacts !== null || text !== null) ? cplugFacts : undefined;
    const agreed = await openModal(
        ConfirmSheet as never,
        updateConsentSheet(
            name,
            text,
            scripts,
            t,
            diff,
            passedFacts,
            permissionDiff,
            flaggedWarning,
            {
                fromVersion: ctx.installed?.version ?? diff?.from_version ?? null,
                toVersion: card.version ?? diff?.to_version ?? null,
                screenshots: card.screenshots ?? [],
                releaseNotes,
            },
        ) as never,
    );
    if (blocked) {
        return { kind: 'failed', outcome: { kind: 'refused', code: 'commit_sha_mismatch' } };
    }
    const permOnly = code === 'permission_widened' && Boolean(permissionDiff);
    const flaggedOnly = code === 'cplug_flagged_ack_required' && Boolean(flaggedWarning?.requiresWarningAck);
    const effectiveSha = sha ?? carried?.body_sha ?? '';
    const effectiveDigest = digest ?? carried?.digest;
    if (!agreed || (!effectiveSha && !permOnly && !flaggedOnly)) {
        return {
            kind: 'failed',
            outcome: {
                kind: 'refused',
                code: code === 'permission_widened' || code === 'cplug_flagged_ack_required' ? code : 'consent_required',
            },
        };
    }
    const consent: UpdateConsent & Record<string, unknown> = { body_sha: effectiveSha };
    if (effectiveDigest) consent.digest = effectiveDigest;
    if (requiresConsent || scripts.length || carried?.scripts) consent.scripts = true;
    if (permissionDiff?.requiresReconsent || code === 'permission_widened' || carried?.accept_permission_escalation) {
        consent.accept_permission_escalation = true;
    }
    if (
        flaggedWarning?.requiresWarningAck ||
        code === 'cplug_flagged_ack_required' ||
        carried?.cplug_flagged_ack ||
        carried?.acknowledge_flagged
    ) {
        consent.cplug_flagged_ack = true;
        consent.acknowledge_flagged = true;
    }
    try {
        return { kind: 'updated', row: await send({ expected_revision: revision, consent: consent as UpdateConsent }) };
    } catch (retryError) {
        const retryCode = refusalCodeOf(retryError);
        if (
            retryCode === 'permission_widened' ||
            retryCode === 'cplug_flagged_ack_required' ||
            retryCode === 'consent_required'
        ) {
            return acceptNewText(ctx, revision, retryError, send, consent);
        }
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
        const code = refusalCodeOf(error);
        if (code === 'commit_sha_mismatch') {
            if (permissionDiffFromError(error)) {
                return acceptNewText(ctx, revision, error, (sent) => host.applyUpdate(installId, sent));
            }
            return { kind: 'failed', outcome: { kind: 'refused', code: 'commit_sha_mismatch' } };
        }
        if (code === 'consent_required' || code === 'permission_widened' || code === 'cplug_flagged_ack_required') {
            return acceptNewText(ctx, revision, error, (sent) => host.applyUpdate(installId, sent));
        }
        return { kind: 'failed', outcome: ledgerFailure(error) };
    }
}
