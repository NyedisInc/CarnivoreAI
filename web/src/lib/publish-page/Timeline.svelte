
<script lang="ts">
    import { untrack } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { reduced } from './motion';
    import type { ItemRecord } from './list-model';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { timelineInputOf } from './side-data';
    import { buildTimeline, whenText } from './timeline-model';
    import TimelineStep from './TimelineStep.svelte';
    import './side.css';

    interface Props extends PageProps { rec: ItemRecord }
    const { store, t, rec }: Props = $props();

    const input = $derived(timelineInputOf(store, rec));
    const items = $derived(buildTimeline(input, t));
    const open = $derived(store.mid?.ev ?? '');

    const seen = new Map<string, Set<string>>();
    const keys = $derived(items.map((i) => i.key));
    const fresh = $derived.by((): Set<string> => {
        const before = seen.get(rec.location);
        return before && !reduced() ? new Set(keys.filter((k) => !before.has(k))) : new Set();
    });
    $effect(() => {
        const list = keys;
        const location = rec.location;
        untrack(() => seen.set(location, new Set(list)));
    });

    const asked = new Set<string>();
    $effect(() => {
        for (const row of input.rows) {
            if (store.reports[row.id] || asked.has(row.id)) continue;
            if (row.events.some((e) => e.what === 'gate_failed')) {
                asked.add(row.id);
                void store.loadReport(row.id);
            }
        }
    });
</script>

<Panel label={t('publish.page.timeline.label')} aux={t('publish.page.timeline.aux')}>
    {#if items.length === 0 && store.failure.facts}
        <p class="d-note" data-tone="yellow" role="alert">{store.failure.facts}</p>
    {:else}
    <ol class="d-log" aria-label={t('publish.page.timeline.list_aria')}>
        {#each items as item (item.key)}
            {#if item.kind === 'fold'}
                <li class="d-ev" data-key={item.key} data-pp="TimelineFold">
                    <div class="d-ev__mark"><span class="d-mk"><Icon name="chevron-right" size={13} /></span></div>
                    <div class="d-ev__body">
                        <details class="d-fold">
                            <summary class="pp-ident">{item.summary}</summary>
                            <ul class="d-list-plain">
                                {#each item.lines as line, i (i)}<li><span class="pp-ident">{line.title}</span><span>{whenText(line.ts, t)}</span></li>{/each}
                            </ul>
                        </details>
                    </div>
                </li>
            {:else}
                <TimelineStep entry={item} current={open === item.key} fresh={fresh.has(item.key)} {t} onOpen={(key) => store.openEvent(key)} />
            {/if}
        {/each}
    </ol>
    {/if}
</Panel>
