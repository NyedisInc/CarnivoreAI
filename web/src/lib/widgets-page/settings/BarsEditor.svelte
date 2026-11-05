
<script lang="ts">
    import { tick } from 'svelte';
    import { Button } from '../../base';
    import type { Translate } from '../../sessions/types';
    import { railStores } from '../../session-rail/rail-store.svelte';
    import { RAIL_EDGES, type RailEdge } from '../../session-rail/rail-model';
    import { widgetBars } from '../../widget-bars/bar-settings.svelte';
    import { other } from '../bar-placement';
    import { barName, moveKey, takeOutKey } from '../bar-run';
    import MockBar from './MockBar.svelte';
    import MockLayout from './MockLayout.svelte';
    import { dockedPx, editCaption, mockKeys, type MockKey } from './mock-model';

    interface Props { t: Translate }
    const { t }: Props = $props();

    const view = $derived(widgetBars.view);
    const keys = $derived({ side: mockKeys(railStores.side.items, t), bottom: mockKeys(railStores.bottom.items, t) });
    let picked = $state<{ edge: RailEdge; key: string } | null>(null);
    const current = $derived.by<{ edge: RailEdge; key: MockKey } | null>(() => {
        const found = picked ? keys[picked.edge].find((one) => one.key === picked?.key) : undefined;
        return picked && found ? { edge: picked.edge, key: found } : null;
    });

    const label = $derived(t('widgets.settings.edit.label'));
    const press = (edge: RailEdge, key: string): void => { picked = picked?.edge === edge && picked.key === key ? null : { edge, key }; };
    let root = $state<HTMLElement | null>(null);
    async function act(kind: 'move' | 'take_out'): Promise<void> {
        const at = current;
        if (!at) return;
        const to = other(at.edge);
        picked = null;
        await (kind === 'move' ? moveKey : takeOutKey)(at.edge, at.key.key, at.key.title, t);
        await tick();
        const keyIn = (edge: RailEdge): HTMLElement | undefined => [...(root?.querySelectorAll<HTMLElement>(`.wp-mockbar--${edge} .wp-key`) ?? [])].find((el) => el.dataset['key'] === at.key.key);
        const hint = root?.querySelector<HTMLElement>('.wp-edit__hint');
        const target = kind === 'move' ? (keyIn(to) ?? keyIn(at.edge)) : (keyIn(at.edge) ?? hint);
        const active = document.activeElement;
        if (active === document.body || (active && root?.contains(active))) target?.focus();
    }
</script>

<div class="wp-edit" bind:this={root}>
    <MockLayout sidePx={dockedPx('side', view)} bottomPx={dockedPx('bottom', view)} {label} {t}>
        {#each RAIL_EDGES as edge (edge)}
            {#if view[edge].show}
                <MockBar {edge} size={view[edge].size} keys={keys[edge]} label={barName(edge, t)} selected={current?.edge === edge ? current.key.key : ''} onPress={(key) => press(edge, key)} />
            {/if}
        {/each}
    </MockLayout>

    <div class="wp-edit__keys" role="group" aria-label={t('widgets.settings.edit.keys')}>
        {#each RAIL_EDGES as edge (edge)}
            {#each view[edge].show ? keys[edge] : [] as one (one.key)}
                <Button variant="row" data-k="edit-key" data-edge={edge} aria-pressed={current?.edge === edge && current.key.key === one.key} onclick={() => press(edge, one.key)}>{t('widgets.settings.edit.caption', { bar: barName(edge, t), items: one.title })}</Button>
            {/each}
        {/each}
    </div>

    <div class="wp-edit__actions" role="group" aria-label={t('widgets.settings.edit.actions')}>
        
        <span class="wp-edit__picked" role="status">{current ? t('widgets.settings.edit.selected', { widget: current.key.title }) : ''}</span>
        {#if current}
            <Button size="sm" data-k="edit-move" onclick={() => void act('move')}>{t('widgets.page.bars.move', { bar: barName(other(current.edge), t) })}</Button>
            <Button size="sm" data-k="edit-take-out" onclick={() => void act('take_out')}>{t('widgets.page.bars.take_out', { bar: barName(current.edge, t) })}</Button>
        {:else}
            <span class="wp-edit__hint" tabindex="-1">{t('widgets.settings.edit.select')}</span>
        {/if}
    </div>

    <ul class="wp-edit__captions">
        {#each RAIL_EDGES as edge (edge)}
            {@const caption = editCaption(view[edge].show, keys[edge])}
            <li class="wp-edit__caption" class:wp-edit__slot={caption.kind === 'empty'} data-edge={edge}>
                {#if caption.kind === 'items'}{t('widgets.settings.edit.caption', { bar: barName(edge, t), items: caption.names })}
                {:else if caption.kind === 'hidden'}{t('widgets.settings.edit.hidden', { bar: barName(edge, t) })}
                {:else}{barName(edge, t)}: {t('widgets.settings.edit.empty')}{/if}
            </li>
        {/each}
    </ul>
</div>
