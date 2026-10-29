
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Button } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import type { Cell } from './api';
    import './matrix.css';

    interface Props {
        t?: Translate;
        cell: Cell | undefined;
        name: string;
        label?: string;
        why?: '' | 'in_app' | 'health';
        showSource?: boolean;
        cellId: string;
        onToggle: (next: boolean) => void;
        onReset?: () => void;
    }
    const { t = reactiveT, cell, name, label = '', why = '', showSource = true, cellId, onToggle, onReset }: Props = $props();

    const locked = $derived(cell?.locked === true || why !== '');
    const pinned = $derived(cell?.source === 'local');
    const reason = $derived(why !== '' ? t(`settings.notify.matrix.lock.${why}.short`) : locked ? t('settings.notify.matrix.lock.short') : '');
    const tip = $derived(why !== '' ? t(`settings.notify.matrix.lock.${why}`) : '');
</script>

<span class="mx-cell" class:mx-cell--row={label !== ''} data-mx-cell={cellId} data-source={cell?.source ?? 'none'} title={tip || undefined}>
    <Check {label} ariaLabel={name} checked={cell?.value === true} disabled={locked || cell === undefined} data-mx="check" onToggle={onToggle} />
    <span class="mx-cell__meta">
        {#if reason}
            <span class="mx-why" data-mx="why">{reason}</span>
        {:else if pinned}
            <span class="mx-badge" data-mx="local-badge">{t('settings.notify.matrix.local')}</span>
            {#if onReset}<Button variant="quiet" size="sm" data-mx="reset" onclick={onReset}>{t('settings.notify.matrix.reset')}</Button>{/if}
        {:else if showSource && cell}
            <span class="mx-src" data-mx="source">{t(`settings.notify.matrix.source.${cell.source}`)}</span>
        {/if}
    </span>
</span>
