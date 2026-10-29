
<script lang="ts">
    import ItemNoteForm from './ItemNoteForm.svelte';
    import { t } from '../i18n/index.svelte';

    interface Props {
        itemId: string;
        signedIn: boolean;
    }

    const { itemId, signedIn }: Props = $props();

    let open = $state(false);
    let panel = $state<HTMLElement | null>(null);
    let trigger = $state<HTMLElement | null>(null);

    $effect(() => {
        if (open) panel?.showPopover();
    });

    function onOutside(event: PointerEvent): void {
        if (!open) return;
        const target = event.target as Node | null;
        if (panel?.contains(target) || trigger?.contains(target)) return;
        open = false;
    }

    function onKeydown(event: KeyboardEvent): void {
        if (!open || event.key !== 'Escape') return;
        open = false;
        trigger?.focus();
    }
</script>

<svelte:window onpointerdown={onOutside} onkeydown={onKeydown} />

<button
    type="button"
    class="tnp-icon"
    bind:this={trigger}
    aria-haspopup="dialog"
    aria-expanded={open}
    aria-label={t('themes.page.note.open')}
    title={t('themes.page.note.open')}
    data-theme-note-open
    onclick={() => { open = !open; }}
>
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
        <path d="M9 7a3 3 0 0 1 6 0M12 10v11M7 11c-2 0-3 1-3 3M17 11c2 0 3 1 3 3M7 15H4M17 15h3M7 19c-1.5 0-2.5-1-3-2M17 19c1.5 0 2.5-1 3-2M8 10h8a2 2 0 0 1 2 2v3a6 6 0 0 1-12 0v-3a2 2 0 0 1 2-2Z" />
    </svg>
</button>

{#if open}
    <div class="tnp-panel popup-focus" popover="manual" role="dialog" aria-label={t('themes.page.note.heading')} tabindex="-1" bind:this={panel} data-theme-note-popup>
        <ItemNoteForm {itemId} {signedIn} />
        <div class="tnp-foot">
            <button type="button" class="modal-btn modal-btn-secondary" onclick={() => { open = false; trigger?.focus(); }}>{t('community.close')}</button>
        </div>
    </div>
{/if}

<style>
    .tnp-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 34px;
        min-height: 34px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
        background: transparent;
        color: var(--oc-text-secondary);
        cursor: pointer;
    }

    .tnp-icon:hover,
    .tnp-icon[aria-expanded='true'] {
        background: var(--oc-ground-raised);
        color: var(--oc-text-primary);
    }

    .tnp-icon svg {
        fill: none;
        stroke: currentColor;
        stroke-width: 1.6;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .tnp-panel {
        position: fixed;
        inset: auto;
        margin: 0;
        right: 16px;
        bottom: 64px;
        z-index: 50;
        display: flex;
        flex-direction: column;
        gap: 8px;
        box-sizing: border-box;
        width: min(380px, calc(100vw - 32px));
        max-height: calc(100vh - 96px);
        padding: 12px;
        overflow: auto;
    }

    .tnp-foot {
        display: flex;
        justify-content: flex-end;
    }

    .tnp-panel :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }

    @media (max-width: 767px) {
        .tnp-icon {
            min-width: 44px;
            min-height: 44px;
        }
    }
</style>
