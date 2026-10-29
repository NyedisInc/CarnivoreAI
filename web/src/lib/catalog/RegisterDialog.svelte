
<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import type { Translate } from '../sessions/types';
    import { refusalCodeOf } from './install-actions';
    import RegisterFields from './RegisterFields.svelte';
    import { clipChars } from './bounds';
    import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
    import { MAX_DETAIL_CHARS, errorText, type PublishAccount, type PublishHost } from './publish';

    interface Props {
        account: PublishAccount | null;
        /* could not be read */
        failure: string | null;
        host: PublishHost;
        t: Translate;
        onregistered: (handle: string, status: string) => void;
    }

    const { account, failure, host, t, onregistered }: Props = $props();

    let typed = $state('');
    let termsTicked = $state(false);
    let ageTicked = $state(false);
    let registering = $state(false);
    let refusal = $state<string | null>(null);

    const needsHandle = $derived(account !== null && !account.handle);
    const termsCurrent = $derived(
        account !== null && account.terms_accepted !== undefined && account.terms_accepted !== '' && account.terms_accepted === account.terms_version,
    );
    const ready = $derived(
        (termsCurrent || (termsTicked && ageTicked)) && (!needsHandle || typed.trim() !== '') && !registering,
    );

    function refusalSentence(error: unknown): string {
        if (refusalCodeOf(error) === 'submission_invalid') {
            const detail = (error as { detail?: { detail?: unknown } } | null)?.detail?.detail;
            return t(PUBLISH_KEYS.handleInvalid, {
                detail: clipChars(typeof detail === 'string' ? detail : '', MAX_DETAIL_CHARS) ?? '',
            });
        }
        return errorText(error, t) || t(PUBLISH_KEYS.registerFailed);
    }

    async function register(): Promise<void> {
        if (!account || !ready) return;
        registering = true;
        refusal = null;
        try {
            const body: { terms_version?: string; age_16_plus?: boolean; handle?: string } = termsCurrent
                ? {}
                : { terms_version: account.terms_version, age_16_plus: true };
            if (needsHandle) body.handle = typed.trim().toLowerCase();
            const answer = await host.register(body);
            window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
            onregistered(answer.handle, answer.handle_status);
        } catch (error) {
            refusal = refusalSentence(error);
        } finally {
            registering = false;
        }
    }
</script>

<section class="handle" aria-label={t(PUBLISH_KEYS.handleHeading)}>
    <p class="handle__heading">{t(PUBLISH_KEYS.handleHeading)}</p>
    {#if failure}
        <p class="handle__note handle__note--out" role="status">
            {t(PUBLISH_KEYS.handleFailed, { reason: failure })}
        </p>
    {:else if !account}
        <p class="handle__note">{t(PUBLISH_KEYS.skillsLoading)}</p>
    {:else if account.registered && account.handle_status === 'github'}
        <p class="handle__note">{t(PUBLISH_KEYS.handleGithub, { handle: account.handle || (account.login ?? '') })}</p>
    {:else if account.registered && account.handle_status === 'confirmed'}
        <p class="handle__note">{t(PUBLISH_KEYS.handleConfirmed, { handle: account.handle })}</p>
    {:else if account.registered}
        <p class="handle__note">{t(PUBLISH_KEYS.handlePending, { handle: account.handle })}</p>
    {:else}
        <p class="handle__note">{t(needsHandle ? PUBLISH_KEYS.handleLead : PUBLISH_KEYS.handleLeadTerms)}</p>
        <RegisterFields {account} {t} {needsHandle} {termsCurrent} bind:handle={typed} bind:termsTicked bind:ageTicked {refusal} />
        <div class="handle__row">
            <button
                class="modal-btn modal-btn-secondary"
                id="catalog-publish-claim"
                disabled={!ready}
                onclick={() => void register()}
            >{registering ? t(PUBLISH_KEYS.handleClaiming) : t(PUBLISH_KEYS.handleClaim)}</button>
            {#if account.terms_url}
                <a class="handle__terms" href={account.terms_url} target="_blank" rel="noopener noreferrer">{t(PUBLISH_KEYS.registerTermsLink)}</a>
            {/if}
        </div>
    {/if}
</section>

<style>
  @layer components {
    .handle__heading {
        margin: 8px 0 4px;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .handle__note {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .handle__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
    }

    .handle__terms {
        color: var(--oc-cyan);
        font-family: var(--font-mono);
        font-size: 11px;
    }

    .handle__row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 6px;
    }
  }
</style>
