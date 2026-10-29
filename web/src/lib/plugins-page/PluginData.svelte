
<script lang="ts">
    import { ApiError } from '../../opscenter/api/auth.svelte';
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from './cplugs-adapter';
    import { bytesText, purgeBlocked, purgeCplug, type PurgePrice } from './plugin-pane';

    interface Props {
        plugin: CplugItem;
        purge?: (cplugId: string, confirmToken?: string) => Promise<PurgePrice>;
        onPurged?: () => void;
        t: Translate;
    }

    const { plugin, purge = purgeCplug, onPurged, t }: Props = $props();

    let price = $state<PurgePrice | null>(null);
    let done = $state<PurgePrice | null>(null);
    let busy = $state(false);
    let error = $state<string | null>(null);
    const blocked = $derived(purgeBlocked(plugin, t));

    $effect(() => {
        if (blocked !== null) price = null;
    });

    async function call(confirmToken?: string): Promise<PurgePrice | null> {
        busy = true;
        error = null;
        try {
            return await purge(plugin.cplugId, confirmToken);
        } catch (failure) {
            error = refusalText(failure);
            return null;
        } finally {
            busy = false;
        }
    }

    function refusalText(failure: unknown): string {
        const code = failure instanceof ApiError ? ((failure.payload as { detail?: { code?: unknown } } | null)?.detail?.code ?? failure.code) : null;
        if (code === 'purge_stale') return t('plugins.page.data.stale');
        if (code === 'cplug_enabled') return t('plugins.page.data.blocked_on', { name: plugin.name });
        return failure instanceof Error && failure.message ? failure.message : t('plugins.page.data.failed');
    }

    async function askPrice(): Promise<void> {
        done = null;
        price = await call();
    }

    async function confirm(): Promise<void> {
        if (!price || blocked !== null) return;
        const landed = await call(price.confirm_token);
        price = null;
        if (!landed) return;
        done = landed;
        onPurged?.();
    }
</script>

<div class="plp-region">
    <h3 class="pl-label">{t('plugins.page.data.stored')}</h3>
    {#if plugin.storageBytes !== null}
        <div class="plp-size" data-plugin-size>
            <span class="plp-size__n">{bytesText(plugin.storageBytes, t)}</span>
        </div>
    {:else}
        <p class="plp-note">{t('plugins.page.data.size_unknown')}</p>
    {/if}
    <dl class="mgr-facts">
        <dt>{t('plugins.page.data.folder')}</dt>
        <dd data-plugin-folder>{t('plugins.page.data.folder_value', { id: plugin.cplugId })}</dd>
    </dl>
</div>
<div class="plp-region" data-plugin-purge>
    <h3 class="pl-label">{t('plugins.page.data.purge')}</h3>
    <p class="plp-brief">{t('plugins.page.data.purge_what', { name: plugin.name })}</p>
    {#if !price}
        <div class="plp-actions">
            {#if blocked}<span class="plp-actions__note" data-purge-blocked>{blocked}</span>{/if}
            <Button variant="danger" data-purge-price disabled={busy || blocked !== null} onclick={() => void askPrice()}
                >{t('plugins.page.data.purge_button')}</Button
            >
        </div>
    {:else}
        <div class="plp-price" data-purge-confirm role="group" aria-label={t('plugins.page.data.purge')}>
            <p class="plp-brief">{t('plugins.page.data.price', { count: price.files, size: bytesText(price.bytes, t), name: plugin.name })}</p>
            <div class="plp-actions">
                <Button data-purge-cancel disabled={busy} onclick={() => (price = null)}>{t('plugins.page.disable.cancel')}</Button>
                <Button variant="danger" data-purge-go disabled={busy || blocked !== null} onclick={() => void confirm()}
                    >{t('plugins.page.data.delete_files', { count: price.files })}</Button
                >
            </div>
        </div>
    {/if}
    {#if error}<p class="plp-fail" data-purge-error>{error}</p>{/if}
    {#if done}<p class="plp-done" data-purge-done>{t('plugins.page.data.done', { count: done.files, size: bytesText(done.bytes, t) })}</p>{/if}
</div>
