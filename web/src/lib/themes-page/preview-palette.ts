
import { themeAssetBase } from './asset-base';
import { isSafeColour } from '../catalog/theme-swatch';
import type { ThemeManifest } from '../../opscenter/api';

export const NEUTRAL = {
    ground: '#0b0d0e',
    raised: '#16191b',
    ink: '#c9ced2',
    mid: '#5b6268',
} as const;

export const ANSI_KEYS = [
    'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white',
    'brightBlack', 'brightRed', 'brightGreen', 'brightYellow',
    'brightBlue', 'brightMagenta', 'brightCyan', 'brightWhite',
] as const;

const IMAGE_NAME = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}\.(png|jpe?g|gif|webp|avif)$/i;

export interface PreviewPalette {
    page: string;
    header: string;
    panel: string;
    border: string;
    fg: string;
    muted: string;
    accent: string;
    success: string;
    warning: string;
    danger: string;
    termBg: string;
    termFg: string;
    cursor: string;
    ansi: string[];
    artwork: string | null;
    background: string | null;
    ascii: boolean;
    hasEffects: boolean;
}

type Source = Record<string, string | undefined>;

export function pick(candidates: readonly (string | undefined)[], fallback: string): string {
    for (const value of candidates) {
        if (isSafeColour(value)) return (value as string).trim();
    }
    return fallback;
}

export function previewPalette(manifest: ThemeManifest): PreviewPalette {
    const v: Source = manifest.cssVars ?? {};
    const x: Source = manifest.xterm ?? {};
    const page = pick([v['--color-bg-page'], v['--color-bg'], x.background], NEUTRAL.ground);
    const panel = pick([v['--color-bg-card'], v['--color-bg-elevated'], v['--color-bg']], NEUTRAL.raised);
    const fg = pick([v['--color-fg'], x.foreground], NEUTRAL.ink);
    const accent = pick([v['--color-accent'], x.cursor, x.brightBlue], NEUTRAL.ink);
    const termBg = pick([x.background, v['--color-bg']], page);
    const termFg = pick([x.foreground, v['--color-fg']], fg);
    const folder = themeAssetBase(manifest.source, manifest.id);
    const image = manifest.background?.image;
    return {
        page,
        header: pick([v['--color-header-bg'], v['--color-bg-elevated'], v['--color-bg']], panel),
        panel,
        border: pick([v['--color-border'], v['--color-border-subtle'], v['--color-fg-faint']], NEUTRAL.mid),
        fg,
        muted: pick([v['--color-fg-muted'], v['--color-fg-subtle'], x.brightBlack], NEUTRAL.mid),
        accent,
        success: pick([v['--color-success'], x.green], accent),
        warning: pick([v['--color-warning'], x.yellow], accent),
        danger: pick([v['--color-danger'], x.red], accent),
        termBg,
        termFg,
        cursor: pick([x.cursor, v['--color-accent']], termFg),
        ansi: ANSI_KEYS.map((key, index) => pick([x[key]], index < 8 ? termFg : fg)),
        artwork: `${folder}/preview.webp`,
        background: typeof image === 'string' && IMAGE_NAME.test(image) ? `${folder}/${encodeURIComponent(image)}` : null,
        ascii: v['--ascii-display'] === 'block',
        hasEffects: typeof manifest.effects === 'string' && manifest.effects.length > 0,
    };
}

export function previewStyle(palette: PreviewPalette): string {
    const props: [string, string][] = [
        ['page', palette.page], ['header', palette.header], ['panel', palette.panel],
        ['border', palette.border], ['fg', palette.fg], ['muted', palette.muted],
        ['accent', palette.accent], ['success', palette.success], ['warning', palette.warning],
        ['danger', palette.danger], ['term-bg', palette.termBg], ['term-fg', palette.termFg],
        ['cursor', palette.cursor],
    ];
    return props.map(([name, value]) => `--p-${name}:${value}`).join(';');
}
