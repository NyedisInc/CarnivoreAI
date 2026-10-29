import { MAX_INSTRUCTIONS_DETAILS, MAX_INSTRUCTIONS_DETAIL_CHARS } from './review';
import type { LoadoutMemberPreview } from './types';

export interface LoadoutMemberFact {
    itemId: string;
    version: string | null;
    kind: string | null;
    title: string;
    needsScripts: boolean;
    installed: boolean;
    writesInstructions: boolean;
    instructionsDetails: string[];
    instructionsMore: number;
}

export interface LoadoutFacts {
    name: string | null;
    description: string | null;
    members: readonly LoadoutMemberFact[];
    anyScripts: boolean;
    anyInstructions: boolean;
    anyTheme: boolean;
    instructionsDetails: string[];
    instructionsMore: number;
}

const NOTHING: LoadoutFacts = {
    name: null,
    description: null,
    members: [],
    anyScripts: false,
    anyInstructions: false,
    anyTheme: false,
    instructionsDetails: [],
    instructionsMore: 0,
};

function trimmed(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function parseLoadoutManifest(
    text: string | null | undefined,
): Record<string, unknown> | null {
    if (typeof text !== 'string' || !text.trim()) return null;
    try {
        const parsed: unknown = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return null;
        }
        return parsed as Record<string, unknown>;
    } catch {
        return null;
    }
}

export function memberFact(
    raw: LoadoutMemberPreview | null | undefined,
): LoadoutMemberFact | null {
    const itemId = trimmed(raw && raw.item_id);
    if (!itemId) return null;
    const scripts = raw && typeof raw.scripts === 'number' ? raw.scripts : null;
    return {
        itemId,
        version: trimmed(raw && raw.version),
        kind: trimmed(raw && raw.kind),
        title: trimmed(raw && raw.title) ?? itemId,
        needsScripts: scripts !== null && scripts > 0,
        installed: (raw && raw.installed) === true,
        writesInstructions: (raw && raw.instructions_write) === true,
        instructionsDetails: detailLines(raw && raw.instructions_details),
        instructionsMore:
            raw && typeof raw.instructions_more === 'number' && raw.instructions_more > 0
                ? Math.floor(raw.instructions_more)
                : 0,
    };
}

function detailLines(raw: unknown): string[] {
    if (!Array.isArray(raw)) return [];
    const lines: string[] = [];
    for (const entry of raw) {
        const text = trimmed(entry);
        if (text && lines.length < MAX_INSTRUCTIONS_DETAILS) {
            lines.push(Array.from(text).slice(0, MAX_INSTRUCTIONS_DETAIL_CHARS).join(''));
        }
    }
    return lines;
}

export function loadoutFacts(
    text: string | null | undefined,
    members: readonly LoadoutMemberPreview[] | null | undefined,
): LoadoutFacts {
    const resolved: LoadoutMemberFact[] = [];
    if (Array.isArray(members)) {
        for (const entry of members) {
            const fact = memberFact(entry);
            if (fact) resolved.push(fact);
        }
    }

    const anyScripts = resolved.some((member) => member.needsScripts);
    const anyInstructions = resolved.some((member) => member.writesInstructions);
    const anyTheme = resolved.some((member) => member.kind === 'theme');
    const allDetails = resolved.flatMap((member) => member.instructionsDetails);
    const instructionsDetails = allDetails.slice(0, MAX_INSTRUCTIONS_DETAILS);
    const instructionsMore =
        resolved.reduce((sum, member) => sum + member.instructionsMore, 0) +
        (allDetails.length - instructionsDetails.length);

    const manifest = parseLoadoutManifest(text);
    if (!manifest) {
        return { ...NOTHING, members: resolved, anyScripts, anyInstructions, anyTheme, instructionsDetails, instructionsMore };
    }

    return {
        name: trimmed(manifest.name),
        description: trimmed(manifest.description),
        members: resolved,
        anyScripts,
        anyInstructions,
        anyTheme,
        instructionsDetails,
        instructionsMore,
    };
}
