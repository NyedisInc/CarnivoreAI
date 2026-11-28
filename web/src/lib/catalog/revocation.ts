import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import { ledgerFailure } from './installed-actions';
import type { CatalogItem, InstalledItem } from './types';

export interface RevocationInfo {
    readonly revoked: boolean;
    readonly reason: string | null;
    readonly since: string | null;
}

export interface RevocationWireFields {
    readonly revoked?: boolean;
    readonly revocation_state?: string | null;
    readonly revocation_reason?: string | null;
    readonly revoked_since?: string | null;
    readonly revoked_at?: string | null;
    readonly status?: string | null;
}

function cleanText(value: unknown): string | null {
    return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

export function revocationOfItem(
    raw: (CatalogItem & RevocationWireFields) | RevocationWireFields | Record<string, unknown> | null | undefined,
): RevocationInfo {
    if (!raw || typeof raw !== 'object') {
        return { revoked: false, reason: null, since: null };
    }
    const obj = raw as RevocationWireFields;
    const state = cleanText(obj.revocation_state)?.toLowerCase();
    const status = cleanText(obj.status)?.toLowerCase();
    const revoked = obj.revoked === true || state === 'revoked' || status === 'revoked';
    const reason = cleanText(obj.revocation_reason);
    const since = cleanText(obj.revoked_since) ?? cleanText(obj.revoked_at);
    return { revoked, reason, since };
}

export function isInstalledRevoked(
    plugin:
        | {
              readonly revoked?: boolean;
              readonly revocation_state?: string | null;
              readonly heldReason?: string | null;
              readonly detail?: string | null;
          }
        | null
        | undefined,
): boolean {
    if (!plugin) return false;
    if (plugin.revoked === true) return true;
    if (cleanText(plugin.revocation_state)?.toLowerCase() === 'revoked') return true;
    const held = cleanText(plugin.heldReason) ?? cleanText(plugin.detail);
    if (!held) return false;
    const lower = held.toLowerCase();
    return lower === 'revoked' || lower.startsWith('revoked:');
}

export function installedRevocationReason(
    plugin:
        | {
              readonly revocationReason?: string | null;
              readonly revocation_reason?: string | null;
              readonly heldReason?: string | null;
              readonly detail?: string | null;
          }
        | null
        | undefined,
): string | null {
    if (!plugin) return null;
    const explicit = cleanText(plugin.revocationReason) ?? cleanText(plugin.revocation_reason);
    if (explicit) return explicit;
    const held = cleanText(plugin.heldReason) ?? cleanText(plugin.detail);
    if (!held) return null;
    if (held.toLowerCase() === 'revoked') return null;
    const prefixMatch = held.match(/^revoked:\s*(.+)$/i);
    return prefixMatch?.[1]?.trim() || held;
}

export async function disableAndUninstallPlugin(args: {
    readonly enabled: boolean | null;
    readonly disable?: () => Promise<unknown>;
    readonly installId: string | null | undefined;
    readonly uninstall: (installId: string) => Promise<unknown>;
    readonly fallbackUninstall?: () => Promise<void> | void;
    readonly row?: InstalledItem | null;
    readonly t: Translate;
}): Promise<{ done: boolean; error: string | null }> {
    try {
        if (args.enabled === true && args.disable) {
            await args.disable();
        }
        const installId = cleanText(args.installId) ?? cleanText(args.row?.install_id);
        if (installId) {
            await args.uninstall(installId);
            return { done: true, error: null };
        }
        if (args.fallbackUninstall) {
            await args.fallbackUninstall();
            return { done: true, error: null };
        }
        return { done: false, error: args.t(SKILL_KEYS.refusedUnknown) };
    } catch (error) {
        const outcome = ledgerFailure(error);
        if (outcome.kind === 'unsupported') return { done: false, error: args.t(SKILL_KEYS.refusedUnsupported) };
        return { done: false, error: refusalMessage(outcome.kind === 'refused' ? outcome.code : '', args.t) };
    }
}
