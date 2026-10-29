
<script lang="ts">
    import { ELITE_KEYS } from '../../../../../client/js/labels/warez-elite.js';
    import { openEliteScreen } from '../../elite/elite-host';
    import KindMark from '../KindMark.svelte';
    import Icon from '../../../opscenter/ui/Icon.svelte';
    import SearchField from '../../../opscenter/ui/SearchField.svelte';
    import type { Translate } from '../../sessions/types';
    import { isReadonly } from '../readonly';
    import { buildMenu, type MenuRow, type MenuSources } from './model';
    import { nodeKey, type MenuKind, type MenuNode } from './route';

    interface Props {
        sources: MenuSources;
        node: MenuNode;
        phone?: boolean;
        find?: string;
        onClearFind?: () => void;
        onNavigate: (node: MenuNode) => void;
        t: Translate;
    }

    const { sources, node, phone = false, find = '', onClearFind, onNavigate, t }: Props = $props();

    const readonly = isReadonly();

    let typed = $state('');
    const query = $derived(phone ? typed : find);
    let opened = $state<Record<string, boolean>>({});
    let tree = $state<HTMLElement | undefined>();
    let tinted = $state<Record<string, boolean>>({});
    const seen = new Map<string, string>();
    const timers = new Set<ReturnType<typeof setTimeout>>();

    const searching = $derived(query.trim() !== '');
    const groups = $derived(buildMenu(sources, query, t, readonly));
    const ancestor = $derived(node.scope === 'installed' && node.page === 'item' ? nodeKey({ scope: 'installed', page: 'kind', kind: node.kind }) : null);
    const selected = $derived(node.scope === 'installed' && node.page === 'item' ? (searching ? nodeKey({ ...node, tab: undefined }) : ancestor!) : nodeKey(node));

    $effect(() => {
        const changed: string[] = [];
        const walk = (rows: readonly MenuRow[]): void => {
            for (const row of rows) {
                const shown = `${row.count ?? ''}|${row.word ?? ''}`;
                const before = seen.get(row.key);
                if (before !== undefined && before !== shown) changed.push(row.key);
                seen.set(row.key, shown);
                walk(row.children);
            }
        };
        for (const group of groups) walk(group.rows);
        if (changed.length === 0) return;
        for (const key of changed) tinted[key] = true;
        const timer = setTimeout(() => {
            timers.delete(timer);
            for (const key of changed) delete tinted[key];
        }, 650);
        timers.add(timer);
    });
    $effect(() => () => timers.forEach(clearTimeout));

    function isOpen(row: MenuRow): boolean {
        return searching || (!phone && (opened[row.key] === true || row.key === ancestor));
    }

    function pick(row: MenuRow): void {
        if (row.children.length && !searching && !phone) opened[row.key] = true;
        onNavigate(row.node);
    }

    function toggle(event: Event, row: MenuRow): void {
        event.stopPropagation();
        if (!searching && !phone) opened[row.key] = !isOpen(row);
    }

    function visible(): HTMLElement[] {
        return tree ? [...tree.querySelectorAll<HTMLElement>('[role="treeitem"]')] : [];
    }

    function onKeydown(event: KeyboardEvent, row: MenuRow): void {
        const rows = visible();
        const at = rows.indexOf(event.currentTarget as HTMLElement);
        const go = (to: HTMLElement | undefined): void => {
            if (!to) return;
            event.preventDefault();
            to.focus();
        };
        if (event.key === 'ArrowDown') go(rows[at + 1]);
        else if (event.key === 'ArrowUp') go(rows[at - 1]);
        else if (event.key === 'Home') go(rows[0]);
        else if (event.key === 'End') go(rows[rows.length - 1]);
        else if (event.key === 'ArrowRight' && row.children.length) {
            event.preventDefault();
            if (!isOpen(row)) opened[row.key] = true;
            else go(rows[at + 1]);
        } else if (event.key === 'ArrowLeft') {
            event.preventDefault();
            if (row.children.length && isOpen(row) && !searching) opened[row.key] = false;
            else if (row.depth === 2) go(rows.slice(0, at).reverse().find((r) => r.dataset.depth === '1'));
        } else if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            pick(row);
        }
    }
</script>

{#snippet line(row: MenuRow)}
    {@const canOpen = row.children.length > 0}
    {@const open = canOpen && isOpen(row)}
    <div
        class="wm__row"
        class:wm__row--phone={phone}
        class:wm__row--zero={row.zero}
        class:wm__row--child={row.depth === 2}
        class:wm__row--tint={tinted[row.key]}
        role="treeitem"
        tabindex={row.key === selected ? 0 : -1}
        aria-level={row.depth}
        aria-selected={row.key === selected}
        aria-expanded={canOpen ? open : undefined}
        data-key={row.key}
        data-depth={row.depth}
        data-anc={row.key === ancestor ? 'true' : undefined}
        onclick={() => pick(row)}
        onkeydown={(event) => onKeydown(event, row)}
    >
        <button type="button" class="wm__caret" class:wm__caret--none={!canOpen} tabindex="-1" aria-hidden="true" data-toggle onclick={(event) => toggle(event, row)}>
            <svg viewBox="0 0 14 14" aria-hidden="true"><path d="M5 2.5L9.5 7 5 11.5" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
        </button>
        {#if row.kind && row.depth === 1}<span class="wm__glyph"><KindMark kind={row.kind} size="md" bare {t} /></span>
        {:else if row.icon && row.depth === 1}<span class="wm__glyph"><Icon name={row.icon} size={14} /></span>{/if}
        <span class="wm__label" class:wm__label--hit={row.hit && searching}>{row.label}</span>
        {#if row.count !== undefined}<span class="wm__count" data-count>{row.count}</span>{/if}
        {#if row.word}<span class="wm__word" data-word={row.word}>{row.word}</span>{/if}
    </div>
    {#if open}
        {#each row.children as child (child.key)}
            <div class="wm__enter" role="none">{@render line(child)}</div>
        {/each}
    {/if}
{/snippet}

<nav class="wm" class:wm--phone={phone} aria-label={t('warez.menu.label')}>
    {#if phone}
    <div class="wm__search">
        <svg class="wm__lens" viewBox="0 0 14 14" aria-hidden="true"><circle cx="5.5" cy="5.5" r="3.7" fill="none" stroke="currentColor" stroke-width="1.2" /><path d="M8.3 8.3L12 12" stroke="currentColor" stroke-width="1.2" fill="none" /></svg>
        <SearchField value={query} onInput={(next) => (typed = next)} placeholder={t('warez.menu.search')} ariaLabel={t('warez.menu.search')} />
        <span class="wm__sizer" aria-hidden="true">{t('warez.menu.search')}</span>
    </div>
    {/if}
    <div class="wm__tree" role="tree" aria-label={t('warez.menu.label')} bind:this={tree}>
        {#each groups as group (group.id)}
            <h2 class="wm__group" data-group={group.id}>{group.label}</h2>
            <div role="group" aria-label={group.label}>
                {#each group.rows as row (row.key)}
                    {@render line(row)}
                {/each}
            </div>
        {/each}
        {#if groups.length === 0}
            <p class="wm__none" data-none>
                {t('warez.menu.none', { query })}
                <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (phone ? (typed = '') : onClearFind?.())}>{t('warez.menu.clear')}</button>
            </p>
        {/if}
    </div>
    
    {#if !readonly}
    <div class="wm__foot">
        <button type="button" class="wm__elite" id="warez-elite-open" title={t(ELITE_KEYS.open)} aria-label={t(ELITE_KEYS.open)} onclick={() => openEliteScreen()}>&pi;</button>
    </div>
    {/if}
</nav>

<style>
    .wm {
        display: flex;
        flex-direction: column;
        box-sizing: border-box;
        /* padding */
        width: max-content;
        max-width: 300px;
        min-height: 0;
        background: var(--oc-ground-titlerow);
        box-shadow: inset -1px 0 0 0 var(--oc-line-rule);
        font-family: var(--font-mono);
    }

    .wm--phone {
        width: 100%;
        min-width: 0;
        max-width: none;
        height: 100%;
        background: var(--oc-ground-page);
        box-shadow: none;
    }

    .wm__search {
        position: relative;
        flex: none;
        padding: 10px 12px;
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    /* padding */
    .wm__search :global(.oc-page__search) {
        contain: inline-size;
    }

    .wm__sizer {
        display: block;
        height: 0;
        overflow: hidden;
        visibility: hidden;
        white-space: nowrap;
        font-size: 13px;
        padding: 0 28px 0 27px;
    }

    .wm__lens {
        position: absolute;
        left: 20px;
        top: 50%;
        width: 12px;
        height: 12px;
        margin-top: -6px;
        color: var(--oc-text-muted);
        pointer-events: none;
        z-index: 1;
    }

    .wm--phone .wm__lens {
        left: 24px;
    }

    .wm__search :global(.oc-field) {
        padding-left: 26px;
    }

    .wm__search :global(.oc-field) {
        height: 30px;
        box-sizing: border-box;
    }

    .wm--phone .wm__search :global(.oc-field) {
        height: 44px;
    }

    .wm--phone .wm__search {
        padding: 12px 16px;
    }

    .wm__tree {
        flex: 1 1 auto;
        min-height: 0;
        overflow-y: auto;
        padding: 4px 0 24px;
        scrollbar-width: thin;
    }

    .wm__foot {
        flex: none;
        display: flex;
        justify-content: flex-end;
        padding: 2px 8px 6px;
    }

    .wm__elite {
        min-width: 24px;
        height: 24px;
        padding: 0 6px;
        border: 1px solid transparent;
        background: transparent;
        color: var(--oc-text-muted);
        font: inherit;
        font-size: 14px;
        line-height: 1;
        cursor: pointer;
        --_bd: var(--oc-line-rule);
    }

    .wm--phone .wm__elite {
        min-width: 44px;
        height: 44px;
    }

    .wm__elite:hover {
        color: var(--oc-text-secondary);
    }

    .wm__group {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0;
        padding: 16px 12px 6px;
        color: var(--oc-text-muted);
        font-size: 10px;
        line-height: 14px;
        font-weight: 400;
        letter-spacing: 0.8px;
        text-transform: uppercase;
    }

    .wm__group:first-child {
        padding-top: 10px;
    }

    .wm--phone .wm__group {
        padding: 20px 16px 6px;
    }

    .wm--phone .wm__group:first-child {
        padding-top: 10px;
    }

    .wm__row {
        position: relative;
        display: flex;
        align-items: center;
        gap: 6px;
        box-sizing: border-box;
        min-height: 28px;
        padding: 3px 12px;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.3;
        cursor: pointer;
        border: 1px solid transparent;
        --_bd: var(--oc-line-rule);
    }

    .wm__row--child::before {
        content: '';
        position: absolute;
        left: 17px;
        top: 0;
        bottom: 0;
        width: 14px;
        background-image: repeating-linear-gradient(to right, var(--oc-line-faint) 0 1px, transparent 1px 14px);
        pointer-events: none;
        opacity: 0.9;
    }

    .wm__row--child {
        padding-left: 26px;
    }

    .wm__row--phone {
        min-height: 52px;
        padding: 3px 16px;
        font-size: 14px;
    }

    .wm__row--phone.wm__row--child {
        padding-left: 30px;
    }

    .wm__row:hover {
        background: var(--oc-ground-hover);
        color: var(--oc-text-primary);
    }

    .wm__row[data-anc='true'] {
        color: var(--oc-text-bright);
    }

    .wm__row[aria-selected='true'] {
        background: var(--oc-orange-tint);
        color: var(--oc-text-bright);
        box-shadow: inset 2px 0 0 0 var(--oc-orange);
    }

    .wm__row--zero {
        color: var(--oc-text-muted);
    }

    .wm__caret {
        flex: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 14px;
        height: 14px;
        margin: 0;
        padding: 0;
        border: 0;
        background: transparent;
        color: var(--oc-text-muted);
        font: inherit;
        transition: transform 140ms ease;
    }

    .wm--phone .wm__caret {
        width: 20px;
        height: 20px;
    }

    .wm__caret svg {
        width: 10px;
        height: 10px;
    }

    .wm__row[aria-expanded='true'] > .wm__caret {
        transform: rotate(90deg);
    }

    .wm__caret--none {
        visibility: hidden;
    }

    .wm__glyph {
        flex: none;
        display: inline-flex;
        line-height: 0;
    }

    .wm__label {
        flex: 1 1 0;
        min-width: 0;
        overflow-wrap: anywhere;
    }

    .wm__label--hit {
        color: var(--oc-text-bright);
        background: var(--oc-orange-tint);
    }

    .wm__count,
    .wm__word {
        flex: none;
        color: var(--oc-text-muted);
        font-size: 11px;
    }

    .wm__count,
    .wm__word {
        padding-left: 8px;
    }

    .wm__row[data-depth='1'] .wm__label {
        font-size: 12px;
    }

    .wm__word[data-word='on'],
    .wm__word[data-word='global'] {
        color: var(--oc-text-secondary);
    }

    .wm__enter {
        animation: wm-slide 140ms ease-out both;
    }

    @keyframes wm-slide {
        from {
            opacity: 0;
            transform: translateY(-4px);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }

    .wm__row--tint::after {
        content: '';
        position: absolute;
        inset: 0;
        background: var(--oc-orange-tint);
        pointer-events: none;
        opacity: 0;
        animation: wm-tint 600ms ease-out 1;
    }

    @keyframes wm-tint {
        from {
            opacity: 1;
        }
        to {
            opacity: 0;
        }
    }

    .wm__none {
        margin: 0;
        padding: 12px;
        color: var(--oc-text-muted);
        font-size: 12px;
        line-height: 1.5;
    }

    .wm__none :global(button) {
        display: block;
        margin-top: 8px;
    }

    @media (prefers-reduced-motion: reduce) {
        .wm__enter {
            animation: none;
        }

        .wm__row--tint::after {
            animation: none;
            display: none;
        }

        .wm__caret {
            transition: none;
        }
    }
</style>
