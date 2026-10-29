
<script lang="ts">
    import { tick } from 'svelte';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { CommunityHost } from '../community/community';
    import type { Translate } from '../sessions/types';
    import DizBody from './DizBody.svelte';
    import type { DizModel } from './diz-model';
    import * as Ansi from './engine/ansi';
    import * as Art from './engine/art';
    import PaneFrame from './PaneFrame.svelte';

    interface Props {
        model: DizModel | null;
        offline: boolean;
        t: Translate;
        host: CommunityHost;
        say: (text: string) => void;
        onAdd: () => void;
        onTry: () => void;
        onAll: () => void;
    }

    const { model, offline, t, host, say, onAdd, onTry, onAll }: Props = $props();

    const FLASH_MS = 1200;

    let scroller = $state<HTMLElement | null>(null);
    let paneRoot = $state<HTMLElement | null>(null);
    let body = $state<{ comment: () => Promise<boolean>; editing: () => boolean } | null>(null);
    let flashTimer: ReturnType<typeof setTimeout> | null = null;

    const info = $derived(model ? model.id + (offline ? ` ${t(K.dizCached)}` : '') : '');

    let shownId = '';
    $effect(() => {
        const id = model?.id ?? '';
        if (id !== shownId) {
            shownId = id;
            void tick().then(() => { if (scroller) scroller.scrollTop = 0; });
        }
    });

    function skull(node: HTMLElement): void {
        const a = Ansi.el(Art.skull());
        a.style.position = 'relative';
        node.appendChild(a);
    }

    export function scrollBy(dy: number): void {
        scroller?.scrollBy(0, dy);
    }
    export async function comment(): Promise<boolean> {
        return (await body?.comment()) ?? false;
    }
    export function editing(): boolean {
        return body?.editing() ?? false;
    }
    export function flash(): void {
        const el = paneRoot;
        if (!el) return;
        el.scrollIntoView({ block: 'center' });
        const first = el.querySelector<HTMLElement>("a[href],button,input,select,textarea,[tabindex]:not([tabindex='-1'])");
        first?.focus({ preventScroll: true });
        el.removeAttribute('data-flash');
        void el.offsetWidth;
        el.setAttribute('data-flash', '');
        if (flashTimer) clearTimeout(flashTimer);
        flashTimer = setTimeout(() => el.removeAttribute('data-flash'), FLASH_MS);
    }
</script>

<PaneFrame bind:el={paneRoot} title={t(K.dizTitle)} info={model ? info : t(K.dizNone)} active={true} cls="diz" label={t(K.ariaDiz)} live={model?.live ?? t(K.dizNone)}>
        <div class="dz-scroll" tabindex="0" role="region" aria-label={t(K.ariaDizScroll)} bind:this={scroller}>
            {#if model}
                <DizBody bind:this={body} {model} {t} {host} {say} {onAdd} {onTry} {offline} />
            {:else}
                <h2 class="dz-name">{t(K.dizNone)}</h2>
                <p class="dz-p dz-dim">{t(K.emptyView)} {t(K.emptyPressBefore)} <button type="button" class="m1-akey" onclick={onAll}>a</button> {t(K.emptyPressAfter)}</p>
                <div class="dz-skull" aria-hidden="true" use:skull></div>
            {/if}
        </div>
</PaneFrame>
