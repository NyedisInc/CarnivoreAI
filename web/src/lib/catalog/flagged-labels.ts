import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import type { StructuredReviewWarning } from './permission-diff';

export type FlaggedChipTone = 'danger' | 'warn' | 'neutral';

export interface FlaggedChip {
    readonly key: string;
    readonly label: string;
    readonly count: number;
    readonly tone: FlaggedChipTone;
}

export interface FlaggedDetailRow {
    readonly label: string;
    readonly file: string | null;
    readonly detail: string;
}

interface KindMeta {
    readonly labelKey: string;
    readonly tone: FlaggedChipTone;
}

const KNOWN_KINDS: Readonly<Record<string, KindMeta>> = {
    prompt_injection: { labelKey: SKILL_KEYS.flaggedKindPromptInjection, tone: 'danger' },
    credential_access: { labelKey: SKILL_KEYS.flaggedKindCredentialAccess, tone: 'danger' },
    settings_write: { labelKey: SKILL_KEYS.flaggedKindSettingsWrite, tone: 'danger' },
    opaque_payload: { labelKey: SKILL_KEYS.flaggedKindOpaquePayload, tone: 'warn' },
    obfuscation: { labelKey: SKILL_KEYS.flaggedKindObfuscation, tone: 'warn' },
    contains_scripts: { labelKey: SKILL_KEYS.flaggedKindContainsScripts, tone: 'warn' },
    other: { labelKey: SKILL_KEYS.flaggedKindOther, tone: 'neutral' },
};

const PREFIX_RE = /^([a-z][a-z0-9_]{1,32})\s*:\s*(.*)$/i;
const MAX_HEADLINE_CHARS = 150;

function parseLegacyReason(raw: string): { kind: string | null; detail: string } {
    const trimmed = raw.trim();
    const match = PREFIX_RE.exec(trimmed);
    if (!match) return { kind: null, detail: trimmed };
    const candidate = match[1].toLowerCase();
    const rest = match[2].trim();
    if (candidate in KNOWN_KINDS || candidate.includes('_')) {
        return { kind: candidate, detail: rest || trimmed };
    }
    return { kind: null, detail: trimmed };
}

function labelForKind(kind: string, t: Translate): { label: string; tone: FlaggedChipTone } {
    const known = KNOWN_KINDS[kind];
    if (known) {
        return { label: t(known.labelKey), tone: known.tone };
    }
    return { label: kind.replace(/_/g, ' '), tone: 'warn' };
}

export function headlineFromSummary(summary: string | null | undefined): string | null {
    if (!summary) return null;
    const clean = summary.replace(/\s+/g, ' ').trim();
    if (!clean) return null;
    const abbrevRe = /\b(?:dr|mr|mrs|ms|st|vs|etc|e\.g|i\.e)$/i;
    let first = clean;
    const endRe = /[.!?](?=\s+[A-Z]|$)/g;
    let match: RegExpExecArray | null;
    while ((match = endRe.exec(clean)) !== null) {
        const before = clean.slice(0, match.index);
        if (match[0] === '.' && abbrevRe.test(before)) continue;
        first = clean.slice(0, match.index + 1).trim();
        break;
    }
    if (first.length <= MAX_HEADLINE_CHARS) return first;
    const cut = first.slice(0, MAX_HEADLINE_CHARS - 1);
    const lastSpace = cut.lastIndexOf(' ');
    return (lastSpace > 40 ? cut.slice(0, lastSpace) : cut).replace(/[.,;:\s]+$/, '') + '\u2026';
}

export function summarizeFlaggedWarnings(
    warnings: readonly StructuredReviewWarning[],
    warningReasons: readonly string[],
    t: Translate,
): { chips: FlaggedChip[]; details: FlaggedDetailRow[] } {
    const chipMap = new Map<string, { label: string; count: number; tone: FlaggedChipTone }>();
    const details: FlaggedDetailRow[] = [];

    const addChip = (key: string, label: string, tone: FlaggedChipTone) => {
        const existing = chipMap.get(key);
        if (existing) {
            existing.count += 1;
        } else {
            chipMap.set(key, { label, count: 1, tone });
        }
    };

    if (warnings.length > 0) {
        for (const w of warnings) {
            const kind = w.kind.trim().toLowerCase();
            const { label, tone } = labelForKind(kind, t);
            addChip(`kind:${kind}`, label, tone);
            if (w.detail) {
                details.push({ label, file: w.file ?? null, detail: w.detail });
            }
        }
    } else {
        for (const raw of warningReasons) {
            const trimmed = raw.trim();
            if (!trimmed) continue;
            const parsed = parseLegacyReason(trimmed);
            if (parsed.kind) {
                const { label, tone } = labelForKind(parsed.kind, t);
                addChip(`kind:${parsed.kind}`, label, tone);
                details.push({ label, file: null, detail: parsed.detail });
            } else {
                addChip(`text:${trimmed.toLowerCase()}`, trimmed, 'warn');
                details.push({ label: '', file: null, detail: trimmed });
            }
        }
    }

    const toneRank: Record<FlaggedChipTone, number> = { danger: 0, warn: 1, neutral: 2 };
    const chips: FlaggedChip[] = [...chipMap.entries()]
        .map(([key, v]) => ({ key, label: v.label, count: v.count, tone: v.tone }))
        .sort((a, b) => toneRank[a.tone] - toneRank[b.tone]);

    return { chips, details };
}
