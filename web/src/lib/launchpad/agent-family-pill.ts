/* could not */

export const FAMILY_PILL_KEYS = {
    unknownLabel: 'session.agent.family.unknown',
    titleFact: 'session.agent.family.title.fact',
    titleGuess: 'session.agent.family.title.guess',
    titleInferredProcess: 'session.agent.family.title.inferred_process',
    titleUnknown: 'session.agent.family.title.unknown',
} as const;

export type FamilyPillKind = 'fact' | 'guess' | 'unknown';

export interface FamilyPillView {
    kind: FamilyPillKind;
    className: string;
    source: string;
    label: string | null;
    titleKey: string;
    titleParams: Record<string, string>;
}

const GUESS_SOURCES = new Set(['fingerprint', 'derived_deepest', 'inferred_process']);

/* label: ' */
export function familyPillView(
    agentFamily: string | null | undefined,
    agentFamilySource: string | null | undefined,
): FamilyPillView {
    const source = agentFamilySource || 'unknown';
    const isGuess = GUESS_SOURCES.has(source);
    const known = !!agentFamily && source !== 'unknown';

    if (!known) {
        return {
            kind: 'unknown',
            className: 'family-pill--unknown',
            source,
            label: null,
            titleKey: FAMILY_PILL_KEYS.titleUnknown,
            titleParams: {},
        };
    }
    if (isGuess) {
        return {
            kind: 'guess',
            className: 'family-pill--guess',
            source,
            label: agentFamily as string,
            titleKey: source === 'inferred_process'
                ? FAMILY_PILL_KEYS.titleInferredProcess
                : FAMILY_PILL_KEYS.titleGuess,
            titleParams: { source },
        };
    }
    return {
        kind: 'fact',
        className: 'family-pill--fact',
        source,
        label: agentFamily as string,
        titleKey: FAMILY_PILL_KEYS.titleFact,
        titleParams: { family: agentFamily as string },
    };
}
