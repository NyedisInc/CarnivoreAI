/* could not */

export interface ThemeSwatch {
    token: string;
    value: string;
}

export interface ThemeFacts {
    name: string | null;
    swatches: ThemeSwatch[];
    effects: string | null;
}

export const SWATCH_TOKENS: readonly string[] = [
    '--color-bg',
    '--color-bg-elevated',
    '--color-fg',
    '--color-accent',
    '--color-border',
    '--color-success',
    '--color-danger',
];

const HEX_COLOUR = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

const RGB_COLOUR = /^rgba?\(\s*[0-9.,%\s]+\)$/;

const MAX_VALUE_CHARS = 64;

export function isSafeColour(value: unknown): boolean {
    if (typeof value !== 'string') return false;
    const trimmed = value.trim();
    if (!trimmed || trimmed.length > MAX_VALUE_CHARS) return false;
    return HEX_COLOUR.test(trimmed) || RGB_COLOUR.test(trimmed);
}

export function parseThemeManifest(
    text: string | null | undefined,
): Record<string, unknown> | null {
    if (typeof text !== 'string' || !text.trim()) return null;
    try {
        const parsed: unknown = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        return parsed as Record<string, unknown>;
    } catch {
        return null;
    }
}

/* --color- */
export function themeFacts(text: string | null | undefined): ThemeFacts {
    const manifest = parseThemeManifest(text);
    if (!manifest) return { name: null, swatches: [], effects: null };

    const rawName = manifest.name;
    const rawEffects = manifest.effects;
    const vars = manifest.cssVars;
    const declared =
        vars && typeof vars === 'object' && !Array.isArray(vars)
            ? (vars as Record<string, unknown>)
            : {};

    const swatches: ThemeSwatch[] = [];
    for (const token of SWATCH_TOKENS) {
        const value = declared[token];
        if (!isSafeColour(value)) continue;
        swatches.push({ token, value: (value as string).trim() });
    }

    return {
        name: typeof rawName === 'string' && rawName.trim() ? rawName.trim() : null,
        swatches,
        effects:
            typeof rawEffects === 'string' && rawEffects.trim()
                ? rawEffects.trim()
                : null,
    };
}
