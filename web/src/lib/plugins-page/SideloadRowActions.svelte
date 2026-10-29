
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import type { SideloadStore } from './sideload-store.svelte';
    import { refusalText, sourceLine } from './sideload-switch';
    import './plugin-pane.css';

    interface Props {
        store: SideloadStore;
        name: string;
        t: Translate;
    }

    const { store, name, t }: Props = $props();

    const item = $derived(store.item(name));
    const busy = $derived(store.busy[name] === true);
    let error = $state<string | null>(null);
    let resynced = $state<string | null>(null);

    function loadedNewCode(answer: unknown): boolean {
        const a = (answer ?? {}) as { unchanged?: unknown; changed?: unknown };
        return (Array.isArray(a.changed) && a.changed.length > 0) || a.unchanged === false;
    }

    async function resync(): Promise<void> {
        resynced = null;
        const from = item ? sourceLine(item, t) : name;
        const answer = await store.resync(name);
        if (loadedNewCode(answer)) resynced = from;
    }

    async function act(run: () => Promise<void>): Promise<void> {
        error = null;
        try {
            await run();
        } catch (failure) {
            error = refusalText(failure, t);
        }
    }
</script>

{#if item}
    <div class="sideload-row" data-sideload-row={name}>
        <span class="sideload-row__source" title={sourceLine(item, t)} data-sideload-source>{sourceLine(item, t)}</span>
        <Button size="sm" disabled={busy} data-sideload-resync={name} onclick={() => void act(resync)}>
            {t('plugins.page.sideload.resync')}
        </Button>
        <Button size="sm" variant="danger" disabled={busy} data-sideload-remove={name} onclick={() => void act(() => store.remove(name))}>
            {t('plugins.page.sideload.remove')}
        </Button>
        {#if resynced}<p class="plp-warn plp-danger sideload-row__warning" role="status" data-sideload-resynced>{t('plugins.page.sideload.warning.resynced', { source: resynced })}</p>{/if}
        {#if error}<p class="plp__error" role="alert" data-sideload-row-error>{error}</p>{/if}
    </div>
{/if}

<style>
    @layer components {
        .sideload-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1-5);
            min-width: 0;
        }

        .sideload-row__warning {
            flex: 1 1 100%;
            margin: 0;
        }

        .sideload-row__source {
            flex: 1 1 100%;
            min-width: 0;
            overflow: hidden;
            color: var(--oc-text-dim);
            font-family: var(--font-mono);
            font-size: var(--oc-fs-label, 11px);
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    }
</style>
