
export const THEME_TOKENS = [
    'ground-page', 'ground-content', 'ground-panel', 'ground-titlerow', 'ground-field', 'ground-raised',
    'text-primary', 'text-secondary', 'text-dim', 'text-muted',
    'line-hairline', 'line-rule', 'line-frame',
    'cyan', 'green', 'coral', 'orange', 'yellow', 'purple-light', 'series-1',
] as const;

export const FONT_KEY = 'font-mono';
const SAFE_VALUE = /^[#a-zA-Z0-9(),.%/ '"_-]{1,160}$/;

export type ThemeValues = Readonly<Record<string, string>>;

export function readTheme(el: Element = document.body ?? document.documentElement): ThemeValues {
    const style = getComputedStyle(el);
    const out: Record<string, string> = {};
    for (const name of THEME_TOKENS) {
        const value = style.getPropertyValue(`--oc-${name}`).trim();
        if (SAFE_VALUE.test(value)) out[name] = value;
    }
    const font = style.getPropertyValue('--font-mono').trim();
    if (SAFE_VALUE.test(font)) out[FONT_KEY] = font;
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
