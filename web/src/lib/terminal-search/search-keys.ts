
export type KeyAction =
    | 'none'
    | 'open'
    | 'next'
    | 'prev'
    | 'close'
    | 'jump-up'
    | 'jump-down'
    | 'shield';

export type KeyConsume = 'both' | 'stop' | 'none';

export interface KeyDecision {
    action: KeyAction;
    consume: KeyConsume;
}

export interface KeyContext {
    open?: boolean;
    inPanel?: boolean;
    alternate?: boolean;
    screenActive?: boolean;
    modalOpen?: boolean;
}

export interface KeyLike {
    type?: string;
    key?: string;
    metaKey?: boolean;
    ctrlKey?: boolean;
    altKey?: boolean;
    shiftKey?: boolean;
}

const NONE: KeyDecision = { action: 'none', consume: 'none' };

export function route(e: KeyLike | null | undefined, ctx?: KeyContext): KeyDecision {
    if (!e || e.type !== 'keydown') return NONE;
    const c = ctx ?? {};
    const open = !!c.open;
    const inPanel = open && !!c.inPanel;

    const key = e.key;
    const meta = !!e.metaKey;
    const ctrl = !!e.ctrlKey;
    const alt = !!e.altKey;
    const shift = !!e.shiftKey;

    if ((key === 'f' || key === 'F') && !alt && meta !== ctrl) {
        if (ctrl && c.alternate) return NONE;
        if (!open && (!c.screenActive || c.modalOpen)) return NONE;
        return { action: 'open', consume: 'both' };
    }

    if (!open) return NONE;

    if ((key === 'g' || key === 'G') && !alt && (meta || ctrl)) {
        return { action: shift ? 'prev' : 'next', consume: 'both' };
    }

    if (!inPanel) return NONE;

    if (key === 'Escape') return { action: 'close', consume: 'both' };
    if (key === 'Enter') return { action: shift ? 'prev' : 'next', consume: 'both' };
    if (key === 'ArrowUp') return { action: 'jump-up', consume: 'both' };
    if (key === 'ArrowDown') return { action: 'jump-down', consume: 'both' };

    return { action: 'shield', consume: 'stop' };
}

export interface SearchBinding {
    keys: string;
    labelKey: string;
    action: KeyAction;
    sample: KeyLike;
    ctx: KeyContext;
}

const SCREEN: KeyContext = { screenActive: true };
const IN_PANEL: KeyContext = { open: true, inPanel: true };

export const SEARCH_BINDINGS: readonly SearchBinding[] = [
    { keys: 'cmd f / ctrl f', labelKey: 'keys.page.search.open', action: 'open', sample: { type: 'keydown', key: 'f', metaKey: true }, ctx: SCREEN },
    { keys: 'cmd g / ctrl g', labelKey: 'keys.page.search.next', action: 'next', sample: { type: 'keydown', key: 'g', metaKey: true }, ctx: IN_PANEL },
    { keys: 'shift cmd g / shift ctrl g', labelKey: 'keys.page.search.prev', action: 'prev', sample: { type: 'keydown', key: 'g', metaKey: true, shiftKey: true }, ctx: IN_PANEL },
    { keys: 'enter', labelKey: 'keys.page.search.next', action: 'next', sample: { type: 'keydown', key: 'Enter' }, ctx: IN_PANEL },
    { keys: 'shift enter', labelKey: 'keys.page.search.prev', action: 'prev', sample: { type: 'keydown', key: 'Enter', shiftKey: true }, ctx: IN_PANEL },
    { keys: 'up / down', labelKey: 'keys.page.search.jump', action: 'jump-up', sample: { type: 'keydown', key: 'ArrowUp' }, ctx: IN_PANEL },
    { keys: 'esc', labelKey: 'keys.page.search.close', action: 'close', sample: { type: 'keydown', key: 'Escape' }, ctx: IN_PANEL },
];

export interface KeyRoutingTarget {
    isOpen(): boolean;
    containsTarget(node: unknown): boolean;
    alternate(): boolean;
    screenActive(): boolean;
    modalOpen(): boolean;
    open(): void;
    close(): void;
    step(dir: 'next' | 'prev'): void;
    jump(delta: number): void;
}

export function installKeyRouting(targetOrRead: KeyRoutingTarget | (() => KeyRoutingTarget), doc: Document): () => void {
    const onKeyDown = (event: Event): void => {
        const e = event as KeyboardEvent;
        const target = typeof targetOrRead === 'function' ? targetOrRead() : targetOrRead;
        const decision = route(e as KeyLike, {
            open: target.isOpen(),
            inPanel: target.containsTarget(e.target),
            alternate: target.alternate(),
            screenActive: target.screenActive(),
            modalOpen: target.modalOpen(),
        });
        if (decision.action === 'none') return;
        if (decision.consume === 'both') e.preventDefault?.();
        if (decision.consume !== 'none') e.stopPropagation?.();

        switch (decision.action) {
            case 'open':
                target.open();
                break;
            case 'close':
                target.close();
                break;
            case 'next':
            case 'prev':
                target.step(decision.action);
                break;
            case 'jump-up':
                target.jump(-1);
                break;
            case 'jump-down':
                target.jump(1);
                break;
            default:
                break;
        }
    };
    doc.addEventListener('keydown', onKeyDown, true);
    return () => doc.removeEventListener('keydown', onKeyDown, true);
}
