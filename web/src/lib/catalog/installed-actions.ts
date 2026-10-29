import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
import { SKILL_KEYS, isUnsupported } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import { MAX_PATH_CHARS, MAX_SCRIPT_FILES, boundedList, clipChars } from './bounds';
import { refusalCodeOf, refusalPayloadOf } from './install-actions';
import type { CplugFactsData, InstalledItem, UpdateDiff } from './types';

export type LedgerOutcome =
    | { kind: 'ok'; row: InstalledItem | null }
    | { kind: 'stale'; row: InstalledItem | null }
    | { kind: 'refused'; code: string }
    | { kind: 'unsupported' }
    | { kind: 'failed' };

export function revisionOf(row: InstalledItem | null | undefined): number | null {
    if (!row) return null;
    const revision = row.revision;
    return typeof revision === 'number' && Number.isFinite(revision) ? revision : null;
}

export function canWrite(row: InstalledItem | null | undefined): boolean {
    if (!row) return false;
    const id = row.install_id;
    return typeof id === 'string' && id.trim() !== '' && revisionOf(row) !== null;
}

export function ledgerFailure(error: unknown): LedgerOutcome {
    if (isUnsupported(error)) return { kind: 'unsupported' };
    const code = refusalCodeOf(error);
    if (code === 'stale_revision') {
        const body = (error as { body?: Record<string, unknown> | null } | null)?.body ?? null;
        return { kind: 'stale', row: rowFromBody(body) };
    }
    if (code) return { kind: 'refused', code };
    return { kind: 'failed' };
}

function rowFromBody(body: Record<string, unknown> | null): InstalledItem | null {
    if (!body || typeof body !== 'object') return null;
    for (const key of ['row', 'installed', 'item']) {
        const nested = body[key];
        if (nested && typeof nested === 'object') return nested as InstalledItem;
    }
    return typeof body.install_id === 'string' ? (body as InstalledItem) : null;
}

export function offersAutoUpdate(row: InstalledItem | null | undefined): boolean {
    return !!row && row.scope === 'global' && canWrite(row);
}

/* its own sentence */
export function uninstallTargetLines(
    row: InstalledItem | null | undefined,
    t: Translate,
): string[] {
    const targets = row && Array.isArray(row.targets) ? row.targets : [];
    const out: string[] = [];
    for (const target of targets) {
        const path = target && typeof target.path === 'string' ? target.path.trim() : '';
        if (!path) continue;
        const harness = target && typeof target.harness === 'string' ? target.harness.trim() : '';
        if (harness === 'claude') out.push(t(SKILL_KEYS.uninstallTargetClaude, { path }));
        else if (harness === 'codex') out.push(t(SKILL_KEYS.uninstallTargetCodex, { path }));
        else out.push(t(SKILL_KEYS.uninstallTargetUnknown, { harness, path }));
    }
    return out;
}

export interface ConsentText {
    /* could not be read */
    body: string | null;
    sha: string | null;
    digest: string | null;
    scripts: string[];
    diff: UpdateDiff | null;
    requiresConsent: boolean;
    cplugFacts: CplugFactsData | null;
}

function scriptsNamed(body: Record<string, unknown> | null): string[] {
    const listed = body && Array.isArray(body.script_files) ? body.script_files : [];
    return listed.filter(
        (entry): entry is string => typeof entry === 'string' && entry.trim() !== '',
    );
}

export function consentSheetOf(
    sheet: Record<string, unknown> | null | undefined,
): ConsentText {
    const body = sheet && typeof sheet === 'object' ? sheet : null;
    const text = body && typeof body.body === 'string' ? body.body : null;
    const sha = body && typeof body.body_sha === 'string' ? body.body_sha.trim() : '';
    const digest = body && typeof body.digest === 'string' ? body.digest.trim() : '';
    return {
        body: text,
        sha: sha || null,
        digest: digest || null,
        scripts: scriptsNamed(body),
        diff: body && body.diff && typeof body.diff === 'object' ? (body.diff as UpdateDiff) : null,
        requiresConsent: body?.requires_consent === true,
        cplugFacts:
            body && body.cplug_facts && typeof body.cplug_facts === 'object' && !Array.isArray(body.cplug_facts)
                ? (body.cplug_facts as CplugFactsData)
                : null,
    };
}

/* undefined outside a secure context */
export function consentTextOf(error: unknown): ConsentText {
    return consentSheetOf(refusalPayloadOf(error));
}

export function uninstallSheet(
    name: string,
    row: InstalledItem | null,
    t: Translate,
): Record<string, unknown> {
    const paths = uninstallTargetLines(row, t);
    return {
        title: t(SKILL_KEYS.uninstallTitle, { name }),
        lead: t(SKILL_KEYS.uninstallDetail),
        linesHeading: paths.length ? t(SKILL_KEYS.uninstallTargets) : null,
        lines: paths.length ? paths : [t(SKILL_KEYS.uninstallTargetsUnknown)],
        confirmLabel: t(SKILL_KEYS.uninstallConfirm),
        busyLabel: t(SKILL_KEYS.uninstallWorking),
        destructive: true,
        t,
    };
}

export function updateSheet(
    name: string,
    from: string | null,
    to: string | null,
    t: Translate,
    notice: readonly string[] | null = null,
    more = 0,
): Record<string, unknown> {
    const fromTo = t(SKILL_KEYS.updateFromTo, { from: from ?? '', to: to ?? '' });
    return {
        title: t(SKILL_KEYS.updateTitle, { name }),
        lead: notice ? `${fromTo} ${t(SKILL_KEYS.consentInstructionsWrite)}` : fromTo,
        lines: notice ? (more > 0 ? [...notice, t(SKILL_KEYS.consentInstructionsMore, { count: more })] : notice) : [],
        confirmLabel: t(SKILL_KEYS.updateConfirm),
        busyLabel: t(SKILL_KEYS.updateWorking),
        t,
    };
}

export function restoreSheet(name: string, version: string | null, t: Translate): Record<string, unknown> {
    return {
        title: t(BROWSE_KEYS.driftRestoreConfirmTitle, { name }),
        lead: t(BROWSE_KEYS.driftRestoreLead, { version: version ?? '' }),
        confirmLabel: t(BROWSE_KEYS.driftRestoreConfirm),
        busyLabel: t(BROWSE_KEYS.driftRestoreWorking),
        t,
    };
}

export function updateConsentSheet(
    name: string,
    text: string | null,
    scripts: readonly string[],
    t: Translate,
    diff: UpdateDiff | null = null,
    cplugFacts: CplugFactsData | null | undefined = undefined,
): Record<string, unknown> {
    const shipsScripts = scripts.length > 0;
    const isCplug = cplugFacts !== undefined;
    const listed = boundedList(scripts, MAX_SCRIPT_FILES);
    const paths = listed.shown.map((entry) => clipChars(entry, MAX_PATH_CHARS) ?? '');
    const baseLead = t(isCplug ? SKILL_KEYS.updateConsentCplugLead : SKILL_KEYS.updateConsentLead);
    return {
        title: t(SKILL_KEYS.updateTitle, { name }),
        lead: shipsScripts ? `${baseLead} ${t(SKILL_KEYS.consentScriptsRun)}` : baseLead,
        document: text,
        diff,
        cplugFacts,
        documentMissing: text ? null : t(SKILL_KEYS.updateConsentUnavailable),
        linesHeading: shipsScripts ? t(SKILL_KEYS.consentScriptsHeading) : null,
        lines: listed.hidden > 0
            ? [...paths, t(SKILL_KEYS.filesMore, { count: listed.hidden })]
            : paths,
        tickLabel: isCplug
            ? null
            : shipsScripts
              ? t(SKILL_KEYS.consentCheckbox)
              : t(SKILL_KEYS.updateConsentCheckbox),
        confirmLabel: t(SKILL_KEYS.updateConsentConfirm),
        busyLabel: t(SKILL_KEYS.updateWorking),
        t,
    };
}
