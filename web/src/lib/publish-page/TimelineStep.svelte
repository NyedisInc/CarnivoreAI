
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { buttonAttrs } from '../base/classes';
    import type { Translate } from '../sessions/types';
    import CheckMark from './CheckMark.svelte';
    import Ident from './Ident.svelte';
    import StageMark from './StageMark.svelte';
    import { whenText, type TlEntry } from './timeline-model';

    interface Props {
        entry: TlEntry;
        current: boolean;
        fresh: boolean;
        t: Translate;
        onOpen: (key: string) => void;
    }
    const { entry, current, fresh, t, onOpen }: Props = $props();

    const when = $derived(whenText(entry.ts, t));
</script>

<li class="d-ev" class:d-ev--new={fresh} data-key={entry.key} data-pp="TimelineStep">
    <div class="d-ev__mark">
        {#if entry.mark.kind === 'stage'}<StageMark stage={entry.mark.stage} shapeOnly {t} />
        {:else if entry.mark.kind === 'verdict'}<CheckMark result={entry.mark.result} shapeOnly {t} />
        {:else}<span class="d-mk"><Icon name={entry.mark.name} size={13} /></span>{/if}
    </div>
    <div class="d-ev__body">
        {#if entry.open}
            <button type="button" class="d-ev__btn" {...buttonAttrs('row', 'md')} aria-current={current} aria-label={t('publish.page.timeline.step_aria', { title: entry.title, when })} onclick={() => onOpen(entry.key)}>
                <span class="d-ev__title pp-ident"><Ident text={entry.title} /></span>
                {#if entry.meta}<span class="d-ev__meta pp-ident"><Ident text={entry.meta} /></span>{/if}
                <span class="d-ev__when">{when}</span>
                <span class="d-ev__go"><Icon name="chevron-right" size={12} /></span>
            </button>
        {:else}
            <div class="d-ev__btn" data-plain>
                <span class="d-ev__title pp-ident"><Ident text={entry.title} /></span>
                {#if entry.meta}<span class="d-ev__meta pp-ident"><Ident text={entry.meta} /></span>{/if}
                <span class="d-ev__when">{when}</span>
            </div>
        {/if}
    </div>
</li>
