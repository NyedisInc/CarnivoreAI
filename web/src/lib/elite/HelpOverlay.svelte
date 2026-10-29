
<script lang="ts">
    import { onMount } from 'svelte';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { Translate } from '../sessions/types';
    import * as Keys from './engine/keys';

    interface Props {
        t: Translate;
        onClose: () => void;
    }

    const { t, onClose }: Props = $props();

    const sections = Keys.helpModel((id) => t(`warez.elite.keycap.${id}`));
    let dialog = $state<HTMLElement | null>(null);

    function title(scope: string): string {
        return scope === 'global' ? t(K.helpScopeGlobal) : scope === 'board' ? t(K.helpScopeBoard) : scope;
    }

    onMount(() => {
        const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        dialog?.querySelector<HTMLElement>('[data-close]')?.focus();
        return () => {
            if (opener && document.contains(opener)) opener.focus();
        };
    });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (Escape is bound in the key layer's modal scope; a click on the backdrop closes) -->
<div class="k-help" role="dialog" aria-modal="true" aria-label={t(K.ariaHelp)} tabindex="-1" bind:this={dialog} onclick={(e) => { if (e.target === dialog) onClose(); }}>
    <div class="k-help-box">
        <div class="k-help-bar"><span>{t(K.helpTitle)}</span><button type="button" data-close aria-label={t(K.helpClose)} onclick={onClose}>{t(K.helpEsc)}</button></div>
        <div class="k-help-cols">
            {#each sections as s (s.scope)}
                <h3>{title(s.scope)}</h3>
                <ul>
                    {#each s.rows as r (r.combo)}
                        <li><kbd>{r.key}</kbd><span>{r.label}</span></li>
                    {/each}
                </ul>
            {/each}
        </div>
    </div>
</div>
