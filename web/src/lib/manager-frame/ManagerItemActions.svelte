
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
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
                <Button variant="danger" data-mgr-remove-confirm="" onclick={confirm}
                    >{t(MANAGER_KEYS.removeConfirm, { name: item.name })}</Button
                >
                <Button data-mgr-remove-cancel="" onclick={() => (asking = null)}
                    >{t(MANAGER_KEYS.removeCancel)}</Button
                >
            </div>
        {:else}
            <div class="mgr-actions__row">
                {#if onExport}
                    <Button data-mgr-export="" disabled={busy} onclick={() => onExport(item.id)}
                        >{busy ? t(MANAGER_KEYS.working) : t(MANAGER_KEYS.exportAction)}</Button
                    >
                {/if}
                {#if onRemove}
                    <Button
                        variant="danger"
                        data-mgr-remove=""
                        disabled={busy || blocked !== null}
                        aria-describedby={blocked !== null ? `mgr-blocked-${item.id}` : undefined}
                        onclick={() => (asking = item.id)}>{t(MANAGER_KEYS.removeAction)}</Button
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
