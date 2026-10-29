
<script lang="ts">
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { Translate } from '../sessions/types';
    import type { TaggedRow } from './batch';
    import { sizeText } from './file-rows';
    import PaneFrame from './PaneFrame.svelte';

    interface Props {
        rows: readonly TaggedRow[];
        offline: boolean;
        t: Translate;
        onDownload: () => void;
        onUpdate: () => void;
        onClear: () => void;
    }

    const { rows, offline, t, onDownload, onUpdate, onClear }: Props = $props();

    const total = $derived(rows.reduce((s, r) => s + r.size, 0));
    const updates = $derived(rows.filter((r) => r.update).length);
    const info = $derived(t(K.taggedInfo, { n: rows.length }) + (rows.length ? ` ${sizeText(total)}` : ''));
    const totalRuns = $derived.by(() => {
        const mark = (v: string | number): string => `\u0001${v}\u0002`;
        const key = rows.length === 1 ? K.taggedTotalOne : K.taggedTotal;
        return t(key, { size: mark(sizeText(total)), n: mark(rows.length) }).split(/(\u0001[^\u0002]*\u0002)/).filter(Boolean).map((p) => (p.startsWith('\u0001') ? { b: true, s: p.slice(1, -1) } : { b: false, s: p }));
    });
    const live = $derived(rows.length ? t(K.liveTagged, { n: rows.length, size: sizeText(total) }) : t(K.liveNoTagged));
</script>

<PaneFrame title={t(K.taggedTitle)} tag={t(K.callersCrew)} {info} active={rows.length > 0} cls="tagp" label={t(K.ariaTagged)} {live}>
    <div class="tg-body">
        {#if !rows.length}
            <div class="tg-none"><b>0</b> {t(K.taggedNone)}</div>
        {:else}
            <div class="tg-list" tabindex="0" role="region" aria-label={t(K.ariaTaggedScroll)}>
                {#each rows as r (r.id)}
                    <div class="tg-row">
                        <div class="tg-l1"><span class="nm">{r.name}{#if r.update} <span class="mk">{t(K.taggedMark)}</span>{/if}</span><span class="sz">{sizeText(r.size)}</span></div>
                    </div>
                {/each}
            </div>
            <div class="tg-tot">{#each totalRuns as run, i (i)}{#if run.b}<b>{run.s}</b>{:else}{run.s}{/if}{/each}</div>
            <div class="tg-act">
                <button type="button" class="tg-b" disabled={offline} onclick={onDownload}><span class="k">[D]</span> {t(K.taggedDownload)}</button>
                <button type="button" class="tg-b" disabled={offline || !updates} onclick={onUpdate}><span class="k">[U]</span> {t(K.taggedUpdate)}</button>
                <button type="button" class="tg-b" onclick={onClear}><span class="k">[C]</span> {t(K.taggedClear)}</button>
            </div>
            <div class="tg-hint">{t(K.taggedHint)}</div>
        {/if}
    </div>
</PaneFrame>
