
<script lang="ts">
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { CommunityHost } from '../community/community';
    import type { Translate } from '../sessions/types';
    import DizComments from './DizComments.svelte';
    import type { DizModel } from './diz-model';

    interface Props {
        model: DizModel;
        t: Translate;
        host: CommunityHost;
        say: (text: string) => void;
        onAdd: () => void;
        onTry: () => void;
        offline: boolean;
        withClose?: boolean;
        onClose?: () => void;
    }

    const { model: m, t, host, say, onAdd, onTry, offline, withClose = false, onClose }: Props = $props();

    let comments = $state<{ begin: () => Promise<boolean>; editing: () => boolean } | null>(null);

    export async function comment(): Promise<boolean> {
        const ok = (await comments?.begin()) ?? false;
        document.querySelector('#dz-ci')?.scrollIntoView({ block: 'nearest' });
        return ok;
    }
    export function editing(): boolean {
        return comments?.editing() ?? false;
    }
</script>

<h2 class="dz-name">{m.name}</h2>
<div class="dz-slug">{m.byLine}</div>
<div class="dz-tags"><span class="k-tag" data-kind={m.kind}>{m.kindTag}</span> <span class="v-tag" data-v={m.verdict}>{m.verdictTag}</span> <span class="dz-st" data-st={m.stateKind}>{m.stateText}</span></div>
{#if m.rating}
    <div class="dz-m dz-rate">{#if m.rating.stars}<span class="dz-stars">{m.rating.stars}</span>{' '}{/if}{m.rating.text}</div>
{/if}
<div class="dz-acts">
    <button type="button" class="dz-act" data-act="add" aria-keyshortcuts="+" aria-disabled={m.actions.addOffline ? 'true' : undefined} onclick={onAdd}>{m.actions.addLabel}</button>
    {#if m.actions.tryable}
        <button type="button" class="dz-act" data-act="try" aria-keyshortcuts="=" onclick={onTry}>{m.actions.tryLabel}</button>
    {:else}
        <span class="dz-act dz-off">{m.actions.tryLabel}</span>
    {/if}
    {#if withClose}<button type="button" class="dz-act" data-close onclick={onClose}>{t(K.dizClose)}</button>{/if}
    {#if m.dl}<span class="dz-dl dz-dim">{m.dl}</span>{/if}
</div>
<section class="dz-sec"><h3 class="dz-k">{t(K.dizSecBrief)}</h3><p class="dz-p">{m.brief}</p></section>
<section class="dz-sec"><h3 class="dz-k">{t(K.dizSecLink)}</h3><code class="dz-cmd">{m.link}</code></section>
<section class="dz-sec">
    <h3 class="dz-k">{t(K.dizSecVersions)}</h3>
    <div class="dz-r dz-h">{m.versionsHead}</div>
    {#each m.versions as v, i (i)}
        <div class="dz-r">{v.line}{#if v.mark}<span class="dz-mk">{v.mark}</span>{/if}</div>
    {/each}
</section>
<section class="dz-sec">
    <h3 class="dz-k">{t(K.dizSecWorks)}</h3>
    <p class="dz-p">{m.works}</p>
    {#if m.swatches.length}<div class="dz-sw">{#each m.swatches as c, i (i)}<span class="sw" style:background={c} title={c}></span>{/each}</div>{/if}
</section>
<section class="dz-sec">
    <h3 class="dz-k">{t(K.dizSecTrust)}</h3>
    <div class="dz-m" data-v={m.verdict}><span class="dz-vb" aria-hidden="true">{#if m.trust.on}<b>{'▓'.repeat(m.trust.on)}</b>{/if}{'░'.repeat(m.trust.off)}</span> <span class="dz-w">{m.trustWord}</span></div>
    <p class="dz-p dz-dim">{m.trustWhy}</p>
</section>
<section class="dz-sec">
    <h3 class="dz-k">{t(K.dizSecGrade)}</h3>
    <div class="dz-m"><span class="dz-vb" aria-hidden="true">{#if m.grade.on}<b>{'▓'.repeat(m.grade.on)}</b>{/if}{'░'.repeat(m.grade.off)}</span> <span class="dz-w">{m.gradeWord}</span></div>
</section>
<section class="dz-sec"><DizComments bind:this={comments} itemId={m.id} {host} {t} {say} /></section>
{#if offline}<p class="dz-p dz-dim">{t(K.dizOffline)}</p>{/if}
