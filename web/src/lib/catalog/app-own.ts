import { isFirstParty } from '../skills-hub/required-skills';

const APP_OWN_SOURCES: ReadonlySet<string> = new Set(['builtin', 'bundled']);

export function isAppOwnSource(sourceIndexUrl: string | null | undefined): boolean {
    return APP_OWN_SOURCES.has(sourceIndexUrl ?? '');
}

export const isBuiltinTheme = (source: string | null | undefined): boolean => source === 'builtin';

export const isBuiltinPlugin = (tier: string | null | undefined): boolean => tier === 'builtin' || tier === 'core';

export const isBundledSkill = (managedItemIds: readonly (string | null | undefined)[]): boolean => managedItemIds.some((id) => isFirstParty(id));
