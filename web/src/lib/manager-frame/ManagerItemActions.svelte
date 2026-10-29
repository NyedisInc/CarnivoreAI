
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { MANAGER_KEYS } from './manager-model';
    import type { ManagerActionState, ManagerItem } from './types';

    interface Props {
        item: ManagerItem;
        onExport?: (id: string) => void;
        onRemove?: (id: string) => void;
        progress?: ManagerActionState;
        t: Translate;
    }

    const { item, onExport, onRemove, progress, t }: Props = $props();

    let asking = $state<string | null>(null);
    const busy = $derived(progress?.busy === true);
    const blocked = $derived(item.removeBlocked ?? null);

    function confirm(): void {
        asking = null;
        onRemove?.(item.id);
    }
</script>

{#if onExport || onRemove}
    <div class="mgr-actions" role="group" aria-label={t(MANAGER_KEYS.actionsLabel)} data-mgr-actions>
        {#if asking === item.id}
            <p class="oc-notice oc-notice--error" role="alert" data-mgr-question>{t(MANAGER_KEYS.removeQuestion, { name: item.name })}</p>
            <div class="mgr-actions__row">
                <button type="button" class="oc-btn oc-btn--danger" data-mgr-remove-confirm onclick={confirm}
                    >{t(MANAGER_KEYS.removeConfirm, { name: item.name })}</button
                >
                <button type="button" class="oc-btn" data-mgr-remove-cancel onclick={() => (asking = null)}
                    >{t(MANAGER_KEYS.removeCancel)}</button
                >
            </div>
        {:else}
            <div class="mgr-actions__row">
                {#if onExport}
                    <button type="button" class="oc-btn" data-mgr-export disabled={busy} onclick={() => onExport(item.id)}
                        >{busy ? t(MANAGER_KEYS.working) : t(MANAGER_KEYS.exportAction)}</button
                    >
                {/if}
                {#if onRemove}
                    <button
                        type="button"
                        class="oc-btn oc-btn--danger"
                        data-mgr-remove
                        disabled={busy || blocked !== null}
                        aria-describedby={blocked !== null ? `mgr-blocked-${item.id}` : undefined}
                        onclick={() => (asking = item.id)}>{t(MANAGER_KEYS.removeAction)}</button
                    >
                {/if}
            </div>
            {#if onRemove && blocked !== null}
                <p class="mgr-actions__why" id="mgr-blocked-{item.id}" data-mgr-remove-blocked>{blocked}</p>
            {/if}
        {/if}
        {#if progress?.error}
            <p class="oc-notice oc-notice--error" role="alert" data-mgr-error>{progress.error}</p>
        {:else if progress?.exported}
            <p class="oc-notice" role="status" data-mgr-notice>{t(MANAGER_KEYS.exported, { file: progress.exported })}</p>
        {/if}
    </div>
{/if}
