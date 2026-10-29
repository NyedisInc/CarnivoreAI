import { getContext, setContext } from 'svelte';
import type { Translate } from '../sessions/types';
import type { Action } from './validate';

export interface RenderContext {
    readonly data: Record<string, unknown> | undefined;
    readonly t: Translate;
    readonly run: (action: Action) => Promise<void>;
}

const KEY = Symbol('cplug-ui');

export function provide(ctx: RenderContext): void {
    setContext(KEY, ctx);
}

export function useRender(): RenderContext {
    return getContext<RenderContext>(KEY);
}
