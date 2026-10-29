
export interface Role {
    token: string;
    label: string;
}

export interface GroundRole extends Role {
    resting: boolean;
}

export type PairKind = 'text' | 'boundary' | 'step' | 'decorative';

export interface ExtraPair {
    fg: Role;
    bg: GroundRole;
    kind: PairKind;
    min: number;
}

export type Verdict = 'pass' | 'large' | 'fail' | 'info';

export interface Measured {
    fg: string;
    bg: string;
    kind: PairKind;
    resting: boolean;
    min: number;
    ratio: number;
    verdict: Verdict;
}

export interface ThemeSummary {
    failsResting: number;
    failsAll: number;
    measured: number;
    worst: Measured | null;
}

export const AA_TEXT = 4.5;
export const AA_LARGE = 3;
export const MIN_STEP = 1.1;

export const TEXT_ROLES: readonly Role[] = [
    { token: '--oc-text-primary', label: 'primary ink' },
    { token: '--oc-text-secondary', label: 'secondary ink' },
    { token: '--oc-text-muted', label: 'muted ink' },
    { token: '--oc-text-dim', label: 'faint ink' },
    { token: '--oc-orange', label: 'accent' },
    { token: '--oc-green', label: 'success' },
    { token: '--oc-yellow', label: 'warning' },
    { token: '--oc-coral', label: 'danger' },
    { token: '--oc-cyan', label: 'info' },
];

const SUNKEN: GroundRole = { token: '--oc-surface-sunken', label: 'sunken', resting: true };
const BASE: GroundRole = { token: '--oc-surface-base', label: 'base', resting: true };
const RAISED: GroundRole = { token: '--oc-surface-raised', label: 'raised', resting: true };
const ACCENT: GroundRole = { token: '--oc-orange', label: 'accent fill', resting: true };

export const GROUND_ROLES: readonly GroundRole[] = [
    SUNKEN,
    BASE,
    { token: '--oc-surface-band', label: 'band', resting: true },
    RAISED,
    { token: '--oc-surface-overlay', label: 'overlay', resting: false },
    { token: '--oc-ground-panel', label: 'panel (legacy)', resting: true },
    { token: '--oc-ground-card', label: 'card (legacy)', resting: true },
    { token: '--oc-ground-hover', label: 'hover (legacy)', resting: false },
];

export const EXTRA_PAIRS: readonly ExtraPair[] = [
    { fg: { token: '--oc-line-control', label: 'control line' }, bg: SUNKEN, kind: 'boundary', min: AA_LARGE },
    { fg: { token: '--oc-line-control', label: 'control line' }, bg: BASE, kind: 'boundary', min: AA_LARGE },
    { fg: { token: '--oc-line-control', label: 'control line' }, bg: RAISED, kind: 'boundary', min: AA_LARGE },
    { fg: { token: '--oc-line-hairline', label: 'hairline' }, bg: BASE, kind: 'decorative', min: 0 },
    { fg: { token: '--oc-on-accent', label: 'on-accent ink' }, bg: ACCENT, kind: 'text', min: AA_TEXT },
    { fg: { token: '--oc-ground-chrome', label: 'alert button label' }, bg: ACCENT, kind: 'text', min: AA_TEXT },
    { fg: { token: '--oc-state-hover', label: 'hover layer' }, bg: BASE, kind: 'step', min: MIN_STEP },
    { fg: { token: '--oc-state-selected', label: 'selected layer' }, bg: BASE, kind: 'step', min: MIN_STEP },
];

export function luminance(rgb: readonly [number, number, number]): number {
    const linear = (v: number): number => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2]);
}

export function contrastRatio(a: readonly [number, number, number], b: readonly [number, number, number]): number {
    const la = luminance(a);
    const lb = luminance(b);
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    return Math.round(ratio * 100) / 100;
}

export function verdict(ratio: number, kind: PairKind, min: number): Verdict {
    if (kind === 'decorative') return 'info';
    if (ratio >= min) return 'pass';
    if (kind === 'text' && ratio >= AA_LARGE) return 'large';
    return 'fail';
}

export function scopeVars(cssVars: Record<string, string>, allNames: Iterable<string>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const name of allNames) out[name] = 'initial';
    for (const [name, value] of Object.entries(cssVars)) out[name] = String(value);
    return out;
}

export function summarize(rows: readonly Measured[]): ThemeSummary {
    const failing = rows.filter((r) => r.verdict === 'fail' || r.verdict === 'large');
    let worst: Measured | null = null;
    for (const row of rows) {
        if (row.min <= 0) continue;
        if (!worst || row.ratio / row.min < worst.ratio / worst.min) worst = row;
    }
    return {
        failsResting: failing.filter((r) => r.resting).length,
        failsAll: failing.length,
        measured: rows.length,
        worst,
    };
}
