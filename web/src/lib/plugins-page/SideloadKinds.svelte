
<script lang="ts">
    import { isCplugIndexKind } from '../catalog/kind-display';
    import type { Translate } from '../sessions/types';
    import SideloadRowActions from './SideloadRowActions.svelte';
    import type { SideloadStore } from './sideload-store.svelte';
    import { kindKey, kindOf } from './sideload-switch';

    interface Props {
        store: SideloadStore;
        t: Translate;
    }

    const { store, t }: Props = $props();

    const items = $derived(store.status?.items ?? []);
</script>

{#if items.length > 0}
    <ul class="sideload-list" aria-label={t('plugins.page.sideload.list.label')} data-sideload-list>
        {#each items as item, index (`${kindOf(item)}/${item.id}/${index}`)}
            <li class="sideload-list__row" data-sideload-kind-row={item.item_id}>
                <span class="sideload-list__kind" data-sideload-kind>{t(kindKey(kindOf(item)))}</span>
                <span class="sideload-list__name">{item.id}</span>
                {#if !isCplugIndexKind(kindOf(item))}
                    <div class="sideload-list__actions"><SideloadRowActions {store} name={item.id} kind={kindOf(item)} {t} /></div>
                {/if}
            </li>
        {/each}
    </ul>
{/if}

<style>
    @layer components {
        .sideload-list {
            display: flex;
            flex-direction: column;
            margin: 0;
            padding: 0;
            list-style: none;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-label, 11px);
        }

        .sideload-list__row {
            display: grid;
            grid-template-columns: 72px minmax(0, 1fr);
            align-items: center;
            gap: var(--oc-space-1-5) var(--oc-space-3);
            padding: var(--oc-space-1-5) var(--oc-space-4);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
        }

        .sideload-list__kind {
            color: var(--oc-text-secondary);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        .sideload-list__name {
            min-width: 0;
            overflow: hidden;
            color: var(--oc-text-primary);
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .sideload-list__actions {
            grid-column: 2;
            min-width: 0;
        }
    }
</style>
