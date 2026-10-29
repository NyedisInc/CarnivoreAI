
<script lang="ts" module>
    export interface TabDef {
        id: string;
        label: string;
        icon?: string;
        badge?: number | string | null;
        dot?: boolean;
        dotLabel?: string;
        disabled?: boolean;
    }

    export function panelAttrs(idBase: string, id: string) {
        return {
            role: 'tabpanel',
            id: `${idBase}-panel-${id}`,
            'aria-labelledby': `${idBase}-tab-${id}`,
            tabindex: 0,
        } as const;
    }
</script>

<script lang="ts">
    import type { Snippet } from 'svelte';
    import { titleWhenTruncated } from '../../lib/base/truncate';
    import Icon from './Icon.svelte';
    import { fadeEdges, revealSideways } from './scroll-fade';

    interface Props {
        tabs: readonly TabDef[];
        active: string;
        onSelect: (id: string) => void;
        label: string;
        idBase: string;
        class?: string;
        joined?: boolean;
        compact?: boolean;
        collapse?: boolean;
        trailing?: Snippet;
    }

    const { tabs, active, onSelect, label, idBase, class: extra = '', joined = false, compact = false, collapse = false, trailing }: Props = $props();

    let scroller = $state<HTMLElement | null>(null);
    let fadeStart = $state(false);
    let fadeEnd = $state(false);

    function measureFade(): void {
        const el = scroller;
        if (!el) return;
        ({ start: fadeStart, end: fadeEnd } = fadeEdges(el));
    }

    $effect(() => {
        const el = scroller;
        if (!el || typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(measureFade);
        observer.observe(el);
        return () => observer.disconnect();
    });

    $effect(() => {
        void active;
        void tabs.length;
        const el = scroller;
        if (el) revealSideways(el, el.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]'));
        measureFade();
    });

    function onKeydown(event: KeyboardEvent): void {
        const enabled = tabs.filter((def) => !def.disabled).map((def) => def.id);
        if (enabled.length === 0) return;
        const at = enabled.indexOf(active);
        let next = -1;
        if (event.key === 'ArrowRight') next = (at + 1) % enabled.length;
        else if (event.key === 'ArrowLeft') next = (at - 1 + enabled.length) % enabled.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = enabled.length - 1;
        if (next < 0) return;
        event.preventDefault();
        const id = enabled[next] as string;
        onSelect(id);
        queueMicrotask(() => scroller?.querySelector<HTMLElement>(`[data-tab="${id}"]`)?.focus());
    }
</script>

<div class="oc-ptabs {extra}" class:oc-ptabs--joined={joined} class:oc-ptabs--compact={compact} class:oc-ptabs--collapse={collapse} class:oc-ptabs--fade-start={fadeStart} class:oc-ptabs--fade-end={fadeEnd}>
    <div
        class="oc-ptabs__list"
        role="tablist"
        aria-label={label}
        bind:this={scroller}
        onscroll={measureFade}
    >
        {#each tabs as def (def.id)}
            <button
                type="button"
                role="tab"
                use:titleWhenTruncated={'.oc-ptab__label'}
                class="oc-ptab"
                id="{idBase}-tab-{def.id}"
                data-tab={def.id}
                aria-selected={active === def.id}
                aria-controls="{idBase}-panel-{def.id}"
                tabindex={active === def.id ? 0 : -1}
                disabled={def.disabled}
                aria-label={collapse && def.icon ? def.label : undefined}
                title={collapse && def.icon ? def.label : undefined}
                onclick={() => onSelect(def.id)}
                onkeydown={onKeydown}
            >
                {#if def.icon}<span class="oc-ptab__icon"><Icon name={def.icon} size={14} /></span>{/if}
                <span class="oc-ptab__label">{def.label}</span>
                {#if def.badge !== null && def.badge !== undefined}<span class="oc-ptab__badge">{def.badge}</span>{/if}
                {#if def.dot}{#if def.dotLabel}<span class="oc-ptab__dot" role="img" aria-label={def.dotLabel} title={def.dotLabel}></span>{:else}<span class="oc-ptab__dot" aria-hidden="true"></span>{/if}{/if}
            </button>
        {/each}
    </div>
    {#if trailing}<div class="oc-ptabs__trailing">{@render trailing()}</div>{/if}
</div>
