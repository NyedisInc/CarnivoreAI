
<script lang="ts">
    import { onMount } from 'svelte';
    import { Button, Field, IconButton } from '../base';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';

    interface Props {
        name: string;
        rank: string;
        verb: string;
        close: (value: string | null) => void;
    }

    let { name, rank, verb, close }: Props = $props();

    let typed = $state('');
    let cancelButton: HTMLElement | null = $state(null);
    const matches = $derived(typed === name);

    onMount(() => cancelButton?.focus());

    function confirm(): void {
        if (matches) close(typed);
    }
</script>

<ModalShell title={t('leader.confirm.title', { verb })} overlayClass="text-prompt-modal leader-confirm" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('leader.confirm.title', { verb })}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close onclick={() => close(null)} />
        </div>
    {/snippet}
    <div data-leader-confirm>
        <p class="leader-confirm__lost">{t('leader.confirm.lost', { name, rank: t(`leader.rank.${rank}`) })}</p>
        <ul class="leader-confirm__list">
            <li>{t('leader.confirm.memory')}</li>
            <li>{t('leader.confirm.thread')}</li>
            <li>{t('leader.confirm.children')}</li>
        </ul>
        <div class="modal-input-group">
            <label class="modal-label" for="leader-confirm-name">{t('leader.confirm.type', { name })}</label>
            <Field id="leader-confirm-name" block type="text" autocomplete="off" spellcheck="false"
                autocapitalize="off" bind:value={typed} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); confirm(); } }} />
        </div>
    </div>
    {#snippet footer()}
        <Button bind:element={cancelButton} onclick={() => close(null)}>{t('leader.confirm.cancel')}</Button>
        <Button variant="danger" disabled={!matches} data-leader-confirm-go onclick={confirm}>{verb}</Button>
    {/snippet}
</ModalShell>

<style>
    @layer components {
        .leader-confirm__lost { margin: 0 0 var(--oc-space-2); color: var(--oc-text-bright); }
        .leader-confirm__list { margin: 0 0 var(--oc-space-3); padding-left: var(--oc-space-4); color: var(--oc-text-secondary); }
        :global(.leader-confirm .modal-btn-danger:disabled) { opacity: 0.45; cursor: not-allowed; }
    }
</style>
