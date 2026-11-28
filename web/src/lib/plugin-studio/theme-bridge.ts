import { activeThemeId, themeChoices, themeTokens, type ThemeChoice } from '../../plugins/sdk/themes';
import { isSafeThemeValue, themeValuesFromOc, type ThemeValues } from '../cplug-ui/frame-theme';

export interface ResolvedThemePreview {
    themeId: string;
    name: string;
    ocStyle: string;
    themeValues: ThemeValues;
}

function serializeOcVars(tokens: Readonly<Record<string, string>>): string {
    const parts: string[] = [];
    for (const [key, value] of Object.entries(tokens)) {
        if (!key.startsWith('--oc-')) continue;
        if (key.includes(';') || key.includes(':')) continue;
        const trimmed = value.trim();
        if (!trimmed || !isSafeThemeValue(trimmed)) continue;
        parts.push(`${key}: ${trimmed}`);
    }
    return parts.join('; ');
}

export function resolveThemePreview(
    themeId: string,
    choices: readonly ThemeChoice[] = themeChoices(),
    tokenReader: (id: string) => Record<string, string> | null = themeTokens,
): ResolvedThemePreview {
    const tokens = tokenReader(themeId) ?? {};
    const themeValues = themeValuesFromOc(tokens);
    const ocStyle = serializeOcVars(tokens);
    const match = choices.find((c) => c.id === themeId);
    return {
        themeId,
        name: match?.name ?? themeId,
        ocStyle,
        themeValues,
    };
}

export function defaultPreviewThemes(
    choices: readonly ThemeChoice[] = themeChoices(),
    active: string | null = activeThemeId(),
): string[] {
    const ids = choices.map((c) => c.id).filter(Boolean);
    const ordered: string[] = [];
    if (active) ordered.push(active);
    const preferredSecond = ids.includes('matrix') && active !== 'matrix' ? 'matrix' : null;
    if (preferredSecond) ordered.push(preferredSecond);
    for (const id of ids) {
        if (ordered.length >= 2) break;
        if (!ordered.includes(id)) ordered.push(id);
    }
    if (ordered.length === 0) return ['carnivore'];
    return ordered;
}
