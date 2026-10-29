
<script lang="ts">
    import { onMount } from 'svelte';
    import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { refusalCodeOf } from './install-actions';
    import type { CatalogDeviceSession } from './types';

    interface Props {
        host: CatalogHost;
        t: Translate;
    }

    const { host, t }: Props = $props();

    let devices = $state<CatalogDeviceSession[] | null>(null);
    let working = $state(false);
    let refusal = $state<string | null>(null);

    const refusalSentence = $derived(refusal === null ? null : refusalMessage(refusal, t));
    const hasOthers = $derived((devices ?? []).some((d) => !d.current));

    async function load(): Promise<void> {
        if (!host.listCatalogSessions) return;
        try {
            devices = (await host.listCatalogSessions()).sessions;
            refusal = null;
        } catch (error) {
            refusal = refusalCodeOf(error);
        }
    }

    async function revoke(act: () => Promise<unknown>): Promise<void> {
        if (working) return;
        working = true;
        try {
            await act();
            await load();
        } catch (error) {
            refusal = refusalCodeOf(error);
        } finally {
            working = false;
        }
    }

    function since(seconds: number): string {
        return t(SKILL_KEYS.sessionsSince, {
            date: new Date(seconds * 1000).toLocaleDateString(),
        });
    }

    onMount(() => {
        void load();
    });
</script>

{#if devices !== null || refusalSentence}
    <section class="devices" aria-label={t(SKILL_KEYS.sessionsHeading)}>
        <span class="devices__heading">{t(SKILL_KEYS.sessionsHeading)}</span>

        {#if devices !== null}
            {#if devices.length === 0}
                <p class="devices__note">{t(SKILL_KEYS.sessionsNone)}</p>
            {/if}
            {#each devices as device (device.sid)}
                <div class="devices__row" data-session-row={device.sid}>
                    <span class="devices__who">
                        <span class="devices__name">
                            {device.label || t(SKILL_KEYS.sessionsUnnamed)}
                        </span>
                        {#if device.current}
                            <span class="devices__here">{t(SKILL_KEYS.sessionsThisDevice)}</span>
                        {/if}
                        <span class="devices__note">{since(device.created_at)}</span>
                    </span>
                    {#if !device.current && host.revokeCatalogSession}
                        <button
                            type="button"
                            class="modal-btn modal-btn-secondary"
                            disabled={working}
                            onclick={() => void revoke(() => host.revokeCatalogSession!(device.sid))}
                        >
                            {t(SKILL_KEYS.sessionsRevoke)}
                        </button>
                    {/if}
                </div>
            {/each}
            {#if hasOthers && host.revokeOtherCatalogSessions}
                <div class="devices__row">
                    <button
                        type="button"
                        class="modal-btn modal-btn-secondary"
                        disabled={working}
                        onclick={() => void revoke(() => host.revokeOtherCatalogSessions!())}
                    >
                        {t(SKILL_KEYS.sessionsRevokeOthers)}
                    </button>
                </div>
            {/if}
        {/if}

        {#if refusalSentence}
            <p class="devices__note devices__note--out" role="status">{refusalSentence}</p>
        {/if}
    </section>
{/if}

<style>
    .devices {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px var(--cat-gutter);
        border-bottom: 1px solid var(--cat-line);
        background: var(--cat-panel);
    }

    .devices__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .devices__row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
    }

    .devices__who {
        display: flex;
        align-items: baseline;
        gap: 8px;
        flex-wrap: wrap;
        min-width: 0;
    }

    .devices__name {
        color: var(--cat-text);
        font-size: 12px;
        overflow-wrap: anywhere;
    }

    .devices__here {
        color: var(--cat-action);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .devices__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .devices__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    .devices :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }

    @media (max-width: 767px) {
        .devices :global(.modal-btn) {
            min-height: 44px;
        }
    }
</style>
