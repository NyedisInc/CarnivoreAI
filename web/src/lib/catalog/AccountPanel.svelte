
<script lang="ts">
    import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { refusalCodeOf } from './install-actions';
    import CommunitySettings from '../community/CommunitySettings.svelte';
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
    import { browserPublishHost, errorText, MAX_DETAIL_CHARS, type PublishHost } from './publish';
    import { clipChars } from './bounds';

    interface Props {
        host: CatalogHost;
        t: Translate;
        onDeleted: () => void;
        publishHost?: PublishHost;
        /* there is nothing */
        hasHandle?: boolean;
        guest?: boolean;
    }

    const { host, t, onDeleted, publishHost = browserPublishHost(), hasHandle = true, guest = false }: Props = $props();

    async function startConfirm(): Promise<void> {
        confirming = true;
        if (guest) {
            expected = 'delete';
            return;
        }
        try {
            const account = await publishHost.account();
            expected = account.handle || account.login || '';
        } catch {
            expected = '';
        }
    }

    let confirming = $state(false);
    let typed = $state('');
    let expected = $state('');
    const matches = $derived(expected !== '' && typed === expected);

    let renaming = $state(false);
    let wanted = $state('');
    let handleNote = $state<string | null>(null);

    async function renameHandle(): Promise<void> {
        const handle = wanted.trim().toLowerCase();
        if (working || handle === '') return;
        working = true;
        try {
            const done = await publishHost.changeHandle(handle);
            handleNote = t(SKILL_KEYS.accountHandleDone, { handle: done.handle });
            renaming = false;
            wanted = '';
            window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
        } catch (error) {
            handleNote = handleRefusal(error);
        } finally {
            working = false;
        }
    }

    function handleRefusal(error: unknown): string {
        const code = refusalCodeOf(error);
        const body = ((error as { detail?: Record<string, unknown> } | null)?.detail ?? {}) as Record<string, unknown>;
        if (code === 'handle_locked') return t(SKILL_KEYS.accountHandleLocked);
        if (code === 'submissions_pending') return t(SKILL_KEYS.accountHandlePending);
        if (code === 'handle_changed') return t(SKILL_KEYS.accountHandleChanged);
        if (code === 'handle_rename_too_soon') {
            const at = typeof body.next_allowed_at === 'number' ? body.next_allowed_at : null;
            return at === null
                ? t(SKILL_KEYS.accountHandleTooSoonUnknown)
                : t(SKILL_KEYS.accountHandleTooSoon, { when: new Date(at * 1000).toLocaleDateString() });
        }
        if (code === 'submission_invalid') {
            const detail = typeof body.detail === 'string' ? body.detail : '';
            return t(PUBLISH_KEYS.handleInvalid, { detail: clipChars(detail, MAX_DETAIL_CHARS) ?? '' });
        }
        return errorText(error, t) || t(SKILL_KEYS.accountHandleUnavailable);
    }

    let working = $state(false);
    let refusal = $state<string | null>(null);

    const refusalSentence = $derived.by(() => {
        if (refusal === null) return null;
        if (refusal === 'reauth_required') return t(SKILL_KEYS.accountReauth);
        if (refusal === 'confirm_mismatch') return t(SKILL_KEYS.accountMismatch);
        return refusalMessage(refusal, t);
    });

    async function download(): Promise<void> {
        if (working || !host.exportCatalogAccount) return;
        working = true;
        try {
            const document_ = await host.exportCatalogAccount();
            const url = URL.createObjectURL(
                new Blob([JSON.stringify(document_, null, 2)], { type: 'application/json' }),
            );
            const link = document.createElement('a');
            link.href = url;
            link.download = t(SKILL_KEYS.accountExportFile);
            link.click();
            URL.revokeObjectURL(url);
            refusal = null;
        } catch (error) {
            refusal = refusalCodeOf(error);
        } finally {
            working = false;
        }
    }

    async function remove(): Promise<void> {
        if (working || !host.deleteCatalogAccount || !matches) return;
        working = true;
        try {
            await host.deleteCatalogAccount(typed);
            refusal = null;
            onDeleted();
        } catch (error) {
            refusal = refusalCodeOf(error);
        } finally {
            working = false;
        }
    }
</script>

{#if host.exportCatalogAccount || host.deleteCatalogAccount}
    <section class="acct" aria-label={t(SKILL_KEYS.accountHeading)}>
        <span class="acct__heading">{t(SKILL_KEYS.accountHeading)}</span>

        <div class="acct__row">
            {#if host.exportCatalogAccount}
                <button type="button" class="modal-btn modal-btn-secondary" disabled={working} onclick={() => void download()}>
                    {t(SKILL_KEYS.accountExport)}
                </button>
            {/if}
            {#if hasHandle && !guest && !renaming}
                <button
                    type="button"
                    class="modal-btn modal-btn-secondary"
                    id="catalog-account-handle-change"
                    disabled={working}
                    onclick={() => {
                        renaming = true;
                        handleNote = null;
                    }}
                >
                    {t(SKILL_KEYS.accountHandleChange)}
                </button>
            {/if}
            {#if host.deleteCatalogAccount && !confirming}
                <button type="button" class="modal-btn modal-btn-danger" disabled={working} onclick={() => void startConfirm()}>
                    {t(SKILL_KEYS.accountDelete)}
                </button>
            {/if}
        </div>

        {#if renaming}
            <p class="acct__note">{t(SKILL_KEYS.accountHandleLead)}</p>
            <label class="acct__label">
                <span>{t(SKILL_KEYS.accountHandleLabel)}</span>
                <input
                    class="acct__input"
                    id="catalog-account-handle-input"
                    type="text"
                    autocomplete="off"
                    autocapitalize="off"
                    spellcheck="false"
                    bind:value={wanted}
                />
            </label>
            <div class="acct__row">
                <button
                    type="button"
                    class="modal-btn modal-btn-secondary"
                    disabled={working}
                    onclick={() => {
                        renaming = false;
                        wanted = '';
                        handleNote = null;
                    }}
                >
                    {t(SKILL_KEYS.accountHandleCancel)}
                </button>
                <button
                    type="button"
                    class="modal-btn modal-btn-confirm"
                    id="catalog-account-handle-save"
                    disabled={working || wanted.trim() === ''}
                    onclick={() => void renameHandle()}
                >
                    {working ? t(SKILL_KEYS.accountHandleBusy) : t(SKILL_KEYS.accountHandleSave)}
                </button>
            </div>
        {/if}
        {#if handleNote}
            <p class="acct__note acct__note--out" role="status">{handleNote}</p>
        {/if}

        {#if !guest}<CommunitySettings {t} />{/if}
        {#if confirming}
            <p class="acct__note">{t(guest ? 'account.guest.delete_lead' : SKILL_KEYS.accountDeleteLead)}</p>
            <label class="acct__label">
                <span>{t(guest ? 'account.guest.delete_label' : SKILL_KEYS.accountDeleteLabel)}</span>
                <input
                    class="acct__input"
                    type="text"
                    autocomplete="off"
                    autocapitalize="off"
                    spellcheck="false"
                    bind:value={typed}
                />
            </label>
            <div class="acct__row">
                <button
                    type="button"
                    class="modal-btn modal-btn-secondary"
                    disabled={working}
                    onclick={() => {
                        confirming = false;
                        typed = '';
                        refusal = null;
                    }}
                >
                    {t(SKILL_KEYS.accountDeleteCancel)}
                </button>
                <button
                    type="button"
                    class="modal-btn modal-btn-danger"
                    disabled={working || !matches}
                    onclick={() => void remove()}
                >
                    {working ? t(SKILL_KEYS.accountDeleteBusy) : t(SKILL_KEYS.accountDeleteConfirm)}
                </button>
            </div>
        {/if}

        {#if refusalSentence}
            <p class="acct__note acct__note--out" role="status">{refusalSentence}</p>
        {/if}
    </section>
{/if}

<style>
    .acct {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px var(--cat-gutter);
        border-bottom: 1px solid var(--cat-line);
        background: var(--cat-panel);
    }

    .acct__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .acct__row {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
    }

    .acct__label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .acct__input {
        padding: 4px 8px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: var(--cat-raised);
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 12px;
    }

    .acct__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .acct__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    .acct :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }

    @media (max-width: 767px) {
        .acct :global(.modal-btn),
        .acct__input {
            min-height: 44px;
        }
    }
</style>
