
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import './manager-frame.css';
    import { MANAGER_KEYS } from './manager-model';
    import type { ManagerView } from './view-memory';

    interface Props {
        view: ManagerView;
        onView: (next: ManagerView) => void;
        t: Translate;
        shelf?: boolean;
    }

    const { view, onView, t, shelf = false }: Props = $props();
</script>

{#if viewport.narrow}
    {@const next = view === 'grid' ? 'list' : 'grid'}
    {@const label = t(view === 'grid' ? MANAGER_KEYS.viewFlipToList : MANAGER_KEYS.viewFlipToGrid)}
    <button type="button" class="oc-ibtn oc-page__flip" aria-label={label} title={label} data-view-flip={view} onclick={() => onView(next)}>
        <Icon name={shelf ? `shelf-${view}` : view} size={shelf ? 14 : 16} strokeWidth={shelf ? 1.2 : 1.5} />
    </button>
{:else}
<div class="oc-page__view" role="group" aria-label={t(MANAGER_KEYS.viewLabel)}>
    {#each [['grid', MANAGER_KEYS.viewGrid], ['list', MANAGER_KEYS.viewList]] as const as [id, key] (id)}
        <button
            type="button"
            class="oc-ibtn"
            aria-pressed={view === id}
            aria-label={t(key)}
            title={t(key)}
            onclick={() => onView(id)}><Icon name={shelf ? `shelf-${id}` : id} size={14} strokeWidth={shelf ? 1.2 : 1.5} /></button
        >
    {/each}
</div>
{/if}
