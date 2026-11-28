
export const THEME_TOKENS = [
    'ground-page', 'ground-content', 'ground-panel', 'ground-titlerow', 'ground-field', 'ground-raised',
    'text-primary', 'text-secondary', 'text-dim', 'text-muted',
    'line-hairline', 'line-rule', 'line-frame',
    'cyan', 'green', 'coral', 'orange', 'yellow', 'purple-light', 'series-1',
] as const;

export const FRAME_OC_TOKENS = [
    '--oc-border', '--oc-cyan', '--oc-font',
    '--oc-fs-body', '--oc-fs-card-name', '--oc-fs-control', '--oc-fs-figure', '--oc-fs-heading', '--oc-fs-hint',
    '--oc-fs-label', '--oc-fs-micro', '--oc-fs-status',
    '--oc-ground-card', '--oc-ground-chrome', '--oc-ground-content', '--oc-ground-field', '--oc-ground-hover',
    '--oc-ground-page', '--oc-ground-panel', '--oc-ground-raised', '--oc-ground-titlerow',
    '--oc-lh-body', '--oc-lh-tight',
    '--oc-line-button', '--oc-line-button-hover', '--oc-line-control', '--oc-line-faint', '--oc-line-frame',
    '--oc-line-hairline', '--oc-line-panel', '--oc-line-rule',
    '--oc-motion', '--oc-motion-fast',
    '--oc-radius', '--oc-radius-control', '--oc-radius-panel', '--oc-radius-sm',
    '--oc-space-0-5', '--oc-space-1', '--oc-space-1-5', '--oc-space-2', '--oc-space-3', '--oc-space-4',
    '--oc-space-5', '--oc-space-6',
    '--oc-state-hover', '--oc-state-selected',
    '--oc-surface-1', '--oc-surface-2', '--oc-surface-band', '--oc-surface-raised', '--oc-surface-sunken',
    '--oc-text-bright', '--oc-text-dim', '--oc-text-muted', '--oc-text-primary', '--oc-text-secondary',
    '--oc-tracking-caps', '--oc-tracking-label',
    '--oc-orange', '--oc-orange-bright', '--oc-orange-dim', '--oc-orange-tint',
    '--oc-green', '--oc-green-bright', '--oc-green-dim',
    '--oc-coral', '--oc-yellow', '--oc-purple-light', '--oc-series-1',
] as const;

export const FONT_KEY = 'font-mono';
const SAFE_VALUE = /^[#a-zA-Z0-9(),.%/+* '"_-]{1,160}$/;
const ALLOWED_FUNCTIONS: ReadonlySet<string> = new Set([
    'rgb', 'rgba', 'hsl', 'hsla', 'color-mix', 'var', 'clamp', 'min', 'max', 'oklch', 'oklab', 'calc',
]);
const FUNCTION_CALL = /([-a-zA-Z]+)\s*\(/g;

export function isSafeThemeValue(value: string): boolean {
    if (!SAFE_VALUE.test(value)) return false;
    for (const match of value.matchAll(FUNCTION_CALL)) {
        if (!ALLOWED_FUNCTIONS.has((match[1] ?? '').toLowerCase())) return false;
    }
    return true;
}

export type ThemeValues = Readonly<Record<string, string>>;

function readProp(primary: CSSStyleDeclaration, fallback: CSSStyleDeclaration | null, prop: string): string {
    const val = primary.getPropertyValue(prop).trim();
    if (val) return val;
    return fallback ? fallback.getPropertyValue(prop).trim() : '';
}

export function readOcVars(el: Element = document.body ?? document.documentElement): ThemeValues {
    const style = getComputedStyle(el);
    const rootStyle = el === document.body && document.documentElement ? getComputedStyle(document.documentElement) : null;
    const out: Record<string, string> = {};
    for (const prop of FRAME_OC_TOKENS) {
        const value = readProp(style, rootStyle, prop);
        if (isSafeThemeValue(value)) out[prop] = value;
    }
    return out;
}

export function readTheme(el: Element = document.body ?? document.documentElement): ThemeValues {
    const style = getComputedStyle(el);
    const rootStyle = el === document.body && document.documentElement ? getComputedStyle(document.documentElement) : null;
    const out: Record<string, string> = {};
    for (const name of THEME_TOKENS) {
        const value = readProp(style, rootStyle, `--oc-${name}`);
        if (isSafeThemeValue(value)) out[name] = value;
    }
    const font = readProp(style, rootStyle, '--font-mono');
    if (isSafeThemeValue(font)) out[FONT_KEY] = font;
    for (const [prop, value] of Object.entries(readOcVars(el))) {
        out[prop] = value;
    }
    return out;
}

export const readHostTheme = readTheme;

export function themeValuesFromOc(
    tokens: Readonly<Record<string, string>> | null | undefined,
    fallbackFont?: string,
): ThemeValues {
    if (!tokens) return {};
    const out: Record<string, string> = {};
    for (const name of THEME_TOKENS) {
        const value = (tokens[`--oc-${name}`] ?? tokens[name] ?? '').trim();
        if (isSafeThemeValue(value)) out[name] = value;
    }
    const font = (tokens['--oc-font'] ?? tokens[FONT_KEY] ?? fallbackFont ?? '').trim();
    if (isSafeThemeValue(font)) out[FONT_KEY] = font;
    for (const prop of FRAME_OC_TOKENS) {
        const value = (tokens[prop] ?? '').trim();
        if (isSafeThemeValue(value)) out[prop] = value;
    }
    for (const [prop, raw] of Object.entries(tokens)) {
        if (!prop.startsWith('--oc-') || Object.hasOwn(out, prop)) continue;
        const value = raw.trim();
        if (isSafeThemeValue(value)) out[prop] = value;
    }
    return out;
}

export function watchTheme(onChange: (values: ThemeValues) => void): () => void {
    let last = JSON.stringify(readTheme());
    const look = (): void => {
        const values = readTheme();
        const text = JSON.stringify(values);
        if (text === last) return;
        last = text;
        onChange(values);
    };
    if (typeof MutationObserver === 'undefined') return () => undefined;
    const observer = new MutationObserver(look);
    const options = { attributes: true, attributeFilter: ['data-theme', 'style', 'class'] };
    observer.observe(document.documentElement, options);
    if (document.body) observer.observe(document.body, options);
    return () => observer.disconnect();
}
