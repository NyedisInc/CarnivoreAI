
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { MAX_COMMENT_CHARS } from './community';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';

    interface Props {
        t: Translate;
        initial?: string;
        actionKey: string;
        signedOut?: boolean;
        locked?: string | null;
        onsubmit: (body: string) => Promise<string | null>;
        oncancel?: () => void;
    }

    const { t, initial = '', actionKey, signedOut = false, locked = null, onsubmit, oncancel }: Props = $props();

    let body = $state(initial);
    let working = $state(false);
    let failure = $state<string | null>(null);

    const left = $derived(MAX_COMMENT_CHARS - [...body].length);
    const ready = $derived(!signedOut && !locked && !working && body.trim() !== '' && left >= 0);

    async function send(): Promise<void> {
        if (!ready) return;
        working = true;
        failure = null;
        try {
            failure = await onsubmit(body.trim());
            if (failure === null && !oncancel) body = '';
        } finally {
            working = false;
        }
    }
</script>

<div class="cmp">
    <Field multiline block rows={3} data-composer-box aria-label={t('community.composer.label')} placeholder={t('community.composer.placeholder')} disabled={signedOut || !!locked || working} bind:value={body} />
    <div class="cmp__row">
        <span class="cmp__count" class:cmp__count--over={left < 0}>
            {t('community.composer.left', { count: left })}
        </span>
        <span class="cmp__acts">
            {#if oncancel}
                <Button onclick={oncancel}>{t('community.cancel')}</Button>
            {/if}
            <Button variant="confirm" data-composer-send disabled={!ready} onclick={() => void send()}>
                {working ? t('community.working') : t(actionKey)}
            </Button>
        </span>
    </div>
    {#if signedOut}
        <p class="cmp__note">{t('community.signed_out')}</p>
    {/if}
    {#if locked && !signedOut}
        <p class="cmp__note">{locked}</p>
    {/if}
    {#if failure}
        <p class="cmp__note cmp__note--out" role="status">{failure}</p>
    {/if}
</div>

<style>
    .cmp { display: flex; flex-direction: column; gap: 6px; }
    .cmp__row { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
    .cmp__acts { display: flex; gap: 6px; }
    .cmp__count { color: var(--cat-faint); font-family: var(--cat-mono); font-size: 10px; }
    .cmp__count--over { color: var(--cat-failure); }
    .cmp__note { margin: 0; color: var(--cat-muted); font-size: 11px; line-height: 1.45; }
    .cmp__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }
</style>
