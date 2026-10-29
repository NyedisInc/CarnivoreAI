
export type ButtonVariant = 'secondary' | 'confirm' | 'danger' | 'quiet' | 'row';
export type ButtonSize = 'md' | 'sm' | 'icon';
export type TagTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info';

export interface ButtonAttrs {
    'data-btn': ButtonVariant;
    'data-size'?: 'sm' | 'icon';
}

export function buttonAttrs(variant: ButtonVariant, size: ButtonSize): ButtonAttrs {
    return size === 'md' ? { 'data-btn': variant } : { 'data-btn': variant, 'data-size': size };
}

export function tagClass(tone: TagTone): string {
    return tone === 'neutral' ? 'oc-tag' : `oc-tag oc-tag--${tone}`;
}

export type StatTileSize = 'compact' | 'regular';
export type StatTileMode = 'line' | 'flat' | 'graph';
export type StatTileTone = 'up' | 'down' | 'flat' | 'none';
export type StatTileKind = 'value' | 'dim' | 'note';

export interface StatTileLook {
    size: StatTileSize;
    mode: StatTileMode;
    kind: StatTileKind;
    framed: boolean;
    display: boolean;
    editing: boolean;
}

export function statTileClass(look: StatTileLook): string {
    const parts = ['oc-stat-tile'];
    if (look.size === 'compact') parts.push('oc-stat-tile--compact');
    if (look.mode !== 'flat') parts.push(`oc-stat-tile--${look.mode}`);
    if (look.framed) parts.push('oc-stat-tile--framed');
    if (look.display) parts.push('oc-stat-tile--display');
    if (look.editing) parts.push('oc-stat-tile--editing');
    if (look.kind === 'note') parts.push('oc-stat-tile--note');
    return parts.join(' ');
}
