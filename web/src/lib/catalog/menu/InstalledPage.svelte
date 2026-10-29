
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../../sessions/types';
    import InstalledKindScreen from './InstalledKindScreen.svelte';
    import { kindPlural, type MenuSources } from './model';
    import type { MenuKind, MenuNode } from './route';

    interface Props {
        node: Extract<MenuNode, { scope: 'installed' | 'look' }>;
        sources: MenuSources;
        t: Translate;
        onNavigate: (node: MenuNode) => void;
        onChanged?: () => void;
        catalogDetail?: Snippet<[string]>;
    }

    const { node, sources, t, onNavigate, onChanged, catalogDetail }: Props = $props();

    const kind = $derived(node.scope === 'look' ? (node.page === 'consent' ? 'plugin' : 'mod') : node.kind);
    const entries = $derived(node.scope === 'look' && node.page === 'flagged' ? sources.flagged : sources.installed[kind]);
    const entry = $derived(node.scope === 'installed' && node.page === 'item' ? entries.find((e) => e.key === node.key) : undefined);
    const realPage = $derived(node.scope === 'installed' && !entry?.catalogId);
</script>

{#if node.scope === 'installed' && realPage}
    <InstalledKindScreen kind={node.kind} tab={node.page === 'kind' ? node.tab : undefined} focusId={node.page === 'item' ? node.key : null} focusTab={node.page === 'item' ? (node.tab ?? null) : null} {onNavigate} {onChanged} />
{:else}
<div class="wi" data-installed-page={node.scope === 'look' ? `look/${node.page}` : node.page === 'item' ? `${node.kind}/${node.key}` : node.kind}>
    {#if node.scope === 'installed' && node.page === 'item'}
        <header class="wi__head">
            <h2 class="wi__title">{entry?.title ?? node.key}</h2>
            <p class="wi__sub">{kindPlural(node.kind, t)}{#if entry?.word} <span class="wi__word">{entry.word}</span>{/if}</p>
        </header>
        {#if entry?.catalogId && catalogDetail}
            {@render catalogDetail(entry.catalogId)}
        {/if}
    {:else}
        <header class="wi__head">
            <h2 class="wi__title">{node.scope === 'look' ? t(`warez.menu.look.${node.page}`) : kindPlural(kind, t)}</h2>
            <p class="wi__sub">{entries.length}</p>
        </header>
        {#if entries.length === 0}
            <p class="wi__state" role="status" data-installed-empty>{t('warez.installed.empty', { kind: kindPlural(kind, t) })}</p>
            <button type="button" class="modal-btn modal-btn-secondary" onclick={() => onNavigate({ scope: 'store', page: 'kind', kind })}>{t('warez.installed.browse', { kind: kindPlural(kind, t) })}</button>
        {:else}
            <ul class="wi__list">
                {#each entries as item (item.key)}
                    <li class="wi__item">
                        <button type="button" class="wi__open" data-open={item.key} onclick={() => onNavigate({ scope: 'installed', page: 'item', kind: 'kind' in item ? (item.kind as MenuKind) : kind, key: item.key })}>
                            <span class="wi__name">{item.title}</span>
                            {#if item.word}<span class="wi__word">{item.word}</span>{/if}
                        </button>
                    </li>
                {/each}
            </ul>
        {/if}
    {/if}
</div>
{/if}

<style>
    @layer components {
        .wi {
            box-sizing: border-box;
            max-width: 880px;
            min-width: 0;
            padding: 24px 32px 56px;
            font-family: var(--font-mono);
            animation: wi-fade 120ms ease-out both;
        }

        .wi__head {
            margin-bottom: 16px;
        }

        .wi__title {
            margin: 0 0 4px;
            color: var(--oc-text-bright);
            font-size: 16px;
            font-weight: 400;
        }

        .wi__sub {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: 12px;
        }

        .wi__sub .wi__word {
            margin-left: 8px;
        }

        .wi__state {
            margin: 0 0 12px;
            color: var(--oc-text-secondary);
            font-size: 13px;
        }

        .wi__list {
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .wi__item {
            box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
        }

        .wi__open {
            display: flex;
            align-items: center;
            gap: 12px;
            width: 100%;
            min-height: 44px;
            padding: 8px 0;
            border: 0;
            background: transparent;
            color: var(--oc-text-secondary);
            font: inherit;
            font-size: 13px;
            text-align: left;
            cursor: pointer;
        }

        .wi__open:hover {
            color: var(--oc-text-bright);
        }

        .wi__name {
            flex: 1 1 0;
            min-width: 0;
            overflow-wrap: anywhere;
        }

        .wi__word {
            flex: none;
            color: var(--oc-text-muted);
            font-size: 11px;
        }

        @keyframes wi-fade {
            from {
                opacity: 0;
            }
            to {
                opacity: 1;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            .wi {
                animation: none;
            }
        }

        @media (max-width: 767px) {
            .wi {
                padding: 16px 16px 40px;
            }
        }
    }
</style>
