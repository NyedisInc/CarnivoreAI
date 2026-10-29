
export const COLORS = ['cyan', 'violet', 'yellow', 'green', 'coral', 'orange', 'teal', 'rose', 'gold'] as const;

export const GRADIENTS = ['ember', 'tide', 'dusk', 'neon'] as const;

export const ANIMATIONS = ['none', 'shimmer', 'pulse'] as const;

const HEX_COLOUR = /^#[0-9a-fA-F]{6}$/;

export const GRADIENT_STOPS: Record<(typeof GRADIENTS)[number], readonly [string, string]> = {
    ember: ['orange', 'yellow'],
    tide: ['cyan', 'green'],
    dusk: ['violet', 'coral'],
    neon: ['cyan', 'violet'],
};

const FX_WINDOWS = 24;

export interface RowStyle {
    colour: string | null;
    gradient: string | null;
    animation: string | null;
}

export type StylePrefix = 'group' | 'layout';

export function styleAttrs(subject: RowStyle | null, prefix: StylePrefix): string {
    if (!subject) return '';
    const colour = subject.colour ?? '';
    const custom = HEX_COLOUR.test(colour);
    if (!custom && !(COLORS as readonly string[]).includes(colour)) return '';
    const gradient = subject.gradient ?? '';
    const hasGradient = (GRADIENTS as readonly string[]).includes(gradient);
    const inline = custom && !hasGradient
        ? ` style="${prefix === 'group' ? '--band-hue' : '--row-hue'}: ${colour.toLowerCase()}"` : '';
    let out = ` data-${prefix}-colour="${custom ? 'custom' : colour}"${inline}`;
    if (hasGradient) out += ` data-${prefix}-gradient="${gradient}"`;
    const animation = subject.animation ?? '';
    if ((ANIMATIONS as readonly string[]).includes(animation) && animation !== 'none') {
        out += ` data-${prefix}-anim="${animation}"`;
    }
    return out;
}

export function fxHtml(attrs: string, prefix: StylePrefix, text: string): string {
    if (attrs.indexOf(` data-${prefix}-anim="shimmer"`) === -1) return '';
    const escaped = String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    return `<span class="band-fx-host" data-anim-host aria-hidden="true"><span class="band-fx">${`<i data-t="${escaped}"></i>`.repeat(FX_WINDOWS)}</span></span>`;
}

export function nextStyle(style: RowStyle, field: string, value: string): RowStyle {
    const next: RowStyle = { colour: style.colour, gradient: style.gradient || null, animation: style.animation || 'none' };
    if (field === 'colour') { next.colour = value; next.gradient = null; }
    if (field === 'gradient') next.gradient = value;
    if (field === 'animation') next.animation = value;
    return next;
}
