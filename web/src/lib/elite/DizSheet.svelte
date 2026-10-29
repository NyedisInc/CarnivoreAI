
<script lang="ts">
    import { onMount } from 'svelte';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { CommunityHost } from '../community/community';
    import type { Translate } from '../sessions/types';
    import DizBody from './DizBody.svelte';
    import type { DizModel } from './diz-model';
    import * as Art from './engine/art';

    interface Props {
        model: DizModel;
        offline: boolean;
        t: Translate;
        host: CommunityHost;
        say: (text: string) => void;
        onAdd: () => void;
        onTry: () => void;
        onClose: () => void;
        openComment?: boolean;
    }

    const { model, offline, t, host, say, onAdd, onTry, onClose, openComment = false }: Props = $props();

    let dialog = $state<HTMLElement | null>(null);
    let body = $state<{ comment: () => Promise<boolean> } | null>(null);
    let opener: HTMLElement | null = null;

    onMount(() => {
        const a = document.activeElement;
        opener = a instanceof HTMLElement ? a : null;
        const first = dialog?.querySelector<HTMLElement>('[data-close]');
        if (openComment) void body?.comment();
        else first?.focus();
        return () => {
            if (opener && document.contains(opener)) opener.focus();
        };
    });

    function strip(node: HTMLElement): { destroy: () => void } {
        const live = Art.live(node, (cols) => Art.strip1(cols, t(K.dizTitle), {}));
        return { destroy: () => live.destroy() };
    }

    const thenDo = (fn: () => void) => (): void => {
        onClose();
        fn();
    };

    function onKeydown(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            onClose();
        } else if (e.key === 'Tab' && dialog) {
            const f = Array.from(dialog.querySelectorAll<HTMLElement>("button,[tabindex='0'],input")).filter((x) => !(x as HTMLButtonElement).disabled);
            if (!f.length) return;
            const i = f.indexOf(document.activeElement as HTMLElement);
            if (e.shiftKey && i <= 0) {
                e.preventDefault();
                f[f.length - 1]!.focus();
            } else if (!e.shiftKey && i === f.length - 1) {
                e.preventDefault();
                f[0]!.focus();
            }
        }
    }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (the dialog handles Escape and Tab on its keydown; a click on the backdrop closes) -->
<div class="m1-sheet" role="dialog" aria-modal="true" aria-label={t(K.ariaSheet, { name: model.name })} tabindex="-1" bind:this={dialog} onkeydown={onKeydown} onclick={(e) => { if (e.target === dialog) onClose(); }}>
    <div class="m1-sheet-box">
        <div class="sh-art" aria-hidden="true" use:strip></div>
        <div class="sh-body">
            <DizBody bind:this={body} {model} {t} {host} {say} onAdd={thenDo(onAdd)} onTry={thenDo(onTry)} {offline} withClose={true} {onClose} />
        </div>
    </div>
</div>
