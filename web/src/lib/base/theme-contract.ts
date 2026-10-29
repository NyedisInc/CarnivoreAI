import contract from '../../../../client/js/themes/theme-contract.json';

export interface ContractSpec {
    kind: 'color' | 'shadow' | 'font' | 'length';
    required?: boolean;
    min?: number;
    max?: number;
    unit?: string;
}

export interface ThemeContract {
    names: Record<string, ContractSpec>;
    deprecated: Record<string, string | null>;
    forbidden_prefixes: string[];
}

export interface ContractReport {
    unknown: string[];
    baseTokens: string[];
    deprecated: string[];
    missing: string[];
    badValues: string[];
}

export const THEME_CONTRACT = contract as ThemeContract;

const BAD_CHARS = /[;{}]/;
const COLOR = /^(?:#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color-mix|color|var)\(.*\)|[a-zA-Z]+)$/;
const LENGTH = /^(\d+(?:\.\d+)?)(px)?$/;

export function valueProblem(spec: ContractSpec, value: string): string | null {
    const v = value.trim();
    if (!v || BAD_CHARS.test(v)) return 'empty or carries ; { }';
    if (spec.kind === 'color' && !COLOR.test(v)) return 'not a color';
    if (spec.kind === 'length') {
        const m = LENGTH.exec(v);
        if (!m) return 'not a px length';
        const n = Number(m[1]);
        if (n < (spec.min ?? 0)) return `below ${spec.min}px`;
        if (spec.max !== undefined && n > spec.max) return `above ${spec.max}px`;
    }
    return null;
}

export function checkThemeVars(cssVars: Record<string, string>, c: ThemeContract = THEME_CONTRACT): ContractReport {
    const report: ContractReport = { unknown: [], baseTokens: [], deprecated: [], missing: [], badValues: [] };
    for (const name of Object.keys(cssVars).sort()) {
        const spec = c.names[name];
        if (spec) {
            const problem = valueProblem(spec, String(cssVars[name]));
            if (problem) report.badValues.push(`${name}: ${problem}`);
        } else if (name in c.deprecated) {
            report.deprecated.push(name);
        } else if (c.forbidden_prefixes.some((p) => name.startsWith(p))) {
            report.baseTokens.push(name);
        } else {
            report.unknown.push(name);
        }
    }
    for (const [name, spec] of Object.entries(c.names).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
        if (spec.required && !(name in cssVars)) report.missing.push(name);
    }
    return report;
}
