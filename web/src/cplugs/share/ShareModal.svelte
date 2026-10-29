<script lang="ts">
    /* could not */
    import { ModalShell, Glyph } from '../sdk/ui';
    import { isAccountLoaded, isSignedIn, requireAccount, t } from '../sdk';
    import {
        DEFAULT_TTL_SECONDS,
        TTL_CHOICES,
        isRelayUnavailable,
        listAllShares,
        listShares,
        mintShare,
        revokeAllShares,
        revokeShare,
        type MintedShare,
        type ShareRow,
    } from './share-api';

    interface CopyCompatApi {
        copyText(text: string): Promise<{ ok: boolean; method: string }>;
    }

    interface Props {
        sessionId: string;
        close: (value: null) => void;
    }

    let { sessionId, close }: Props = $props();

    let ttl = $state(DEFAULT_TTL_SECONDS);
    let label = $state('');
    let minting = $state(false);
    let minted = $state<MintedShare | null>(null);
    let copied = $state(false);
    let notice = $state('');

    const locked = $derived(isAccountLoaded() && !isSignedIn());

    function signIn(): void {
        void requireAccount({ feature: 'share_link', src: 'share_modal', resume: () => void refresh() });
    }

    let current = $state<ShareRow | null>(null);

    let relayAvailable = $state(false);

    let loaded = $state(false);

    let revoking = $state(false);

    let totalLinks = $state(0);

    let armed = $state(false);

    const ARM_MS = 4000;

    let armTimer: ReturnType<typeof setTimeout> | undefined;

    let urlEl = $state<HTMLInputElement | null>(null);

    /* could not */
    const rowUrl = $derived(
        current === null
            ? null
            : (current.url ??
                  (minted !== null && minted.id === current.id ? minted.url : null)),
    );

    const plainLink = $derived(rowUrl !== null && !rowUrl.includes('#v2.'));

    const COPIED_MS = 1500;

    let copiedTimer: ReturnType<typeof setTimeout> | undefined;

    async function refresh(): Promise<void> {
        try {
            const state = await listShares(sessionId);
            current = state.links[0] ?? null;
            relayAvailable = state.relay_available;
            loaded = true;
        } catch {
            notice = t('cplug.share.list_failed');
            return;
        }
        try {
            totalLinks = (await listAllShares()).length;
        } catch (error) {
            console.error('[share] the install-wide link count could not be read:', error);
            totalLinks = current === null ? 0 : 1;
        }
    }

    async function create(): Promise<void> {
        if (minting) return;
        minting = true;
        notice = '';
        copied = false;
        try {
            minted = await mintShare(sessionId, ttl, label.trim());
            await refresh();
        } catch (error) {
            if (isRelayUnavailable(error)) {
                relayAvailable = false;
            } else {
                notice = t('cplug.share.failed');
            }
        } finally {
            minting = false;
        }
    }

    async function revoke(id: string): Promise<void> {
        if (revoking) return;
        revoking = true;
        notice = '';
        try {
            await revokeShare(sessionId, id);
            if (minted && minted.id === id) minted = null;
            await refresh();
        } catch {
            notice = t('cplug.share.revoke_failed');
        } finally {
            revoking = false;
        }
    }

    async function revokeAll(): Promise<void> {
        if (revoking) return;
        if (!armed) {
            armed = true;
            clearTimeout(armTimer);
            armTimer = setTimeout(() => (armed = false), ARM_MS);
            return;
        }
        clearTimeout(armTimer);
        armed = false;
        revoking = true;
        notice = '';
        try {
            const ended = await revokeAllShares();
            minted = null;
            await refresh();
            notice = t('cplug.share.revoked_all', { count: ended.length });
        } catch {
            notice = t('cplug.share.revoke_all_failed');
        } finally {
            revoking = false;
        }
    }

    /* nothing at all */
    function copy(): void {
        const url = rowUrl;
        if (!url) return;
        notice = '';
        copied = false;
        clearTimeout(copiedTimer);
        const compat = (globalThis as { CopyCompat?: CopyCompatApi }).CopyCompat;
        const clip = (
            globalThis as { navigator?: { clipboard?: { writeText(v: string): Promise<void> } } }
        ).navigator?.clipboard;
        const attempt: Promise<{ ok: boolean }> = compat
            ? compat.copyText(url)
            : clip && typeof clip.writeText === 'function'
              ? clip.writeText(url).then(
                    () => ({ ok: true }),
                    () => ({ ok: false }),
                )
              : Promise.resolve({ ok: false });
        void attempt.then((result) => {
            if (result.ok) {
                copied = true;
                copiedTimer = setTimeout(() => (copied = false), COPIED_MS);
                return;
            }
            copied = false;
            notice = t('cplug.share.copy_manual');
            urlEl?.focus();
            urlEl?.select();
        });
    }

    function rowDetail(row: ShareRow): string {
        return t('cplug.share.expires_at', { when: row.expires_at });
    }

    $effect(() => {
        void refresh();
        return () => {
            clearTimeout(copiedTimer);
            clearTimeout(armTimer);
        };
    });

    const RELAY_RECHECK_MS = 5000;

    $effect(() => {
        if (!loaded || relayAvailable) return;
        const timer = setInterval(() => void refresh(), RELAY_RECHECK_MS);
        return () => clearInterval(timer);
    });
</script>

<ModalShell title={t('cplug.share.title')} onCancel={() => close(null)}>
    <p class="modal-description share-explain">{t('cplug.share.explain')}</p>
    <p class="modal-description" data-share-relay>{t('cplug.share.relay_on')}</p>
    <p class="modal-description" data-share-scrubbed>
        {plainLink ? t('cplug.share.scrubbed_plain') : t('cplug.share.scrubbed')}
    </p>
    <p class="modal-description" data-share-scrub-limit>{t('cplug.share.scrub_limit')}</p>

    <div class="modal-input-group">
        <label class="modal-label" for="share-ttl">{t('cplug.share.ttl')}</label>
        <select id="share-ttl" class="modal-input share-select" bind:value={ttl} data-share-ttl>
            {#each TTL_CHOICES as choice (choice.seconds)}
                <option value={choice.seconds}>
                    {choice.count === undefined
                        ? t(choice.key)
                        : t(choice.key, { count: choice.count })}
                </option>
            {/each}
        </select>
    </div>

    <div class="modal-input-group">
        <label class="modal-label" for="share-label">{t('cplug.share.label')}</label>
        <input
            id="share-label"
            type="text"
            class="modal-input"
            bind:value={label}
            maxlength="80"
            autocomplete="off"
            data-share-label
        />
    </div>

    {#if locked}
        <p class="modal-description share-notice" role="status" data-share-locked>{t('account.lock.share_read_only')}</p>
    {/if}

    {#if loaded && !relayAvailable}
        <p class="modal-description share-notice" role="status" data-share-relay-unavailable>
            {t('cplug.share.relay_unavailable')}
        </p>
    {/if}

    {#if notice}
        <p class="modal-description share-notice" role="status">{notice}</p>
    {/if}

    <h4 class="share-active">{t('cplug.share.active_one')}</h4>
    {#if current === null}
        <p class="modal-description">{t('cplug.share.none')}</p>
    {:else}
        <div class="share-row" data-share-row>
            <span class="share-row-text">
                {current.label ? `${current.label} - ` : ''}{rowDetail(current)}
            </span>
            <div class="share-row-link">
                {#if rowUrl}
                    <input
                        type="text"
                        class="modal-input share-url"
                        readonly
                        bind:this={urlEl}
                        value={rowUrl}
                        data-share-url
                        aria-label={t('cplug.share.link')}
                    />
                    
                    <button
                        type="button"
                        class="modal-btn modal-btn-secondary share-copy"
                        aria-label={copied ? t('cplug.share.copied') : t('cplug.share.copy')}
                        data-copied={copied}
                        onclick={copy}
                    >
                        {#if copied}{t('cplug.share.copied')}{:else}<Glyph name="copy" />{/if}
                    </button>
                {/if}
                <button
                    type="button"
                    class="modal-btn modal-btn-danger share-revoke"
                    data-share-revoke={current.id}
                    disabled={revoking}
                    onclick={() => revoke(current!.id)}
                >{t('cplug.share.revoke')}</button>
            </div>
        </div>
        
        <p class="modal-description">{t('cplug.share.replaces')}</p>
    {/if}

    {#if totalLinks > 0}
        
        <div class="share-all" data-share-all>
            <span class="share-all-text">{t('cplug.share.all_count', { count: totalLinks })}</span>
            <button
                type="button"
                class="modal-btn modal-btn-danger share-revoke-all"
                data-share-revoke-all
                data-armed={armed}
                disabled={revoking}
                onclick={revokeAll}
            >{armed ? t('cplug.share.revoke_all_confirm') : t('cplug.share.revoke_all')}</button>
        </div>
    {/if}

    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" onclick={() => close(null)}>
            {t('cplug.share.close')}
        </button>
        
        {#if locked}
        <button type="button" class="modal-btn modal-btn-primary" data-share-signin onclick={signIn}>{t('account.lock.cta')}</button>
        {:else}
        <button
            type="button"
            class="modal-btn modal-btn-primary"
            disabled={minting || revoking || !relayAvailable}
            data-share-create
            onclick={create}
        >{minting
                ? t('cplug.share.creating')
                : current
                  ? t('cplug.share.replace')
                  : t('cplug.share.create')}</button>
        {/if}
    {/snippet}
</ModalShell>

<style>
    .share-explain {
        margin: 0 0 18px;
    }

    .share-notice {
        color: var(--oc-text-primary);
    }

    .share-select {
        appearance: none;
        -webkit-appearance: none;
        /* padding */
        line-height: normal;
        padding-right: 34px;
        cursor: pointer;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5l3 3 3-3'/></svg>");
        background-repeat: no-repeat;
        background-position: right 12px center;
        background-size: 10px 10px;
    }


    .share-active {
        color: var(--oc-text-secondary);
        margin: 20px 0 8px;
        font-size: 0.9rem;
        font-weight: normal;
        text-transform: lowercase;
    }

    .share-all {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        justify-content: space-between;
        margin-top: 14px;
        padding-top: 10px;
        border-top: var(--oc-border) solid var(--oc-line-panel);
        color: var(--oc-text-secondary);
        font-size: 0.85rem;
    }

    .share-all-text {
        min-width: 0;
    }

    .share-row {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 10px 12px;
        border: var(--oc-border) solid var(--oc-line-panel);
        border-radius: var(--oc-radius-sm);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 0.85rem;
    }

    .share-row-text {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .share-row-link {
        display: flex;
        gap: 8px;
        align-items: stretch;
        min-width: 0;
    }

    .share-url {
        flex: 1;
        min-width: 0;
        font-size: 0.85rem;
        text-overflow: ellipsis;
    }

    .share-copy {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0 12px;
    }

    .share-revoke {
        flex: 0 0 auto;
    }

    @media (max-width: 1023px) {
        .share-copy,
        .share-revoke {
            min-height: 44px;
            min-width: 44px;
        }

        .share-row-link {
            flex-wrap: wrap;
        }

        .share-url {
            flex-basis: 100%;
            min-height: 44px;
        }
    }
</style>
