<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { refusalMessage } from '../../../../client/js/labels/skill.js';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import Check from '../../opscenter/ui/Check.svelte';
    import { Button, Field } from '../base';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { raiseToast } from '../launchpad/recent-open-feedback';
    import { t } from '../i18n/index.svelte';
    import { refusalCodeOf } from '../catalog/install-actions';
    import { isEmailUnconfigured, looksLikeAddress, looksLikeCode, minutesOf, stepAfterRefusal } from '../catalog/email-signin';
    import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
    import type { CatalogAuthSession, EmailFlowStart } from '../catalog/types';
    import { ACCOUNT_FEATURES } from './features';

    const NEW_TAB: Record<string, string> = { target: '_blank', rel: 'noopener noreferrer' };
    import {
        PRIVACY_URL,
        TERMS_URL,
        browserSignInHost,
        consentOf,
        signedInToast,
        type SignInHost,
    } from './signin-flow';

    interface Props {
        feature?: string;
        src?: string;
        close: (value: 'signed_in' | null) => void;
        host?: SignInHost;
    }

    const { feature = '', src = 'menu', close, host = browserSignInHost() }: Props = $props();

    const KEEP_POLLING = [429, 502, 503];

    let news = $state(true);
    let address = $state('');
    let code = $state('');
    let working = $state(false);
    let refusal = $state<string | null>(null);
    let waiting = $state(false);
    let fallbackUrl = $state<string | null>(null);
    let copied = $state(false);
    let codeFlow = $state<EmailFlowStart | null>(null);
    let viaProof = $state(false);
    let emailOff = $state(false);

    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let polling = false;
    let flowId = '';
    let interval = 3;
    let deadline = 0;

    const title = $derived(
        (ACCOUNT_FEATURES as readonly string[]).includes(feature)
            ? t(`account.modal.title.${feature}`)
            : t('account.modal.title.generic'),
    );
    const refusalSentence = $derived(refusal === null ? null : refusalMessage(refusal, t));

    function stopPolling(): void {
        polling = false;
        if (pollTimer !== null) clearTimeout(pollTimer);
        pollTimer = null;
        waiting = false;
    }

    function finish(session: CatalogAuthSession): void {
        stopPolling();
        raiseToast(signedInToast(session.login || address.trim(), t));
        window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
        close('signed_in');
    }

    async function pollOnce(): Promise<void> {
        if (!polling) return;
        pollTimer = null;
        try {
            const answer = await host.pollWeb(flowId);
            if (!polling) return;
            if (answer.mailbox_proof) {
                stopPolling();
                codeFlow = answer.mailbox_proof;
                viaProof = true;
                code = '';
            } else if (answer.status === 'pending') {
                interval = Math.max(1, Number(answer.interval) || interval);
                if (Date.now() > deadline) {
                    stopPolling();
                    refusal = 'flow_expired';
                    return;
                }
                pollTimer = setTimeout(() => void pollOnce(), interval * 1000);
            } else {
                finish(answer as CatalogAuthSession);
            }
        } catch (error) {
            if (!polling) return;
            if (KEEP_POLLING.includes((error as { status?: number })?.status ?? 0)) {
                pollTimer = setTimeout(() => void pollOnce(), interval * 1000);
                return;
            }
            stopPolling();
            refusal = refusalCodeOf(error);
        }
    }

    function onVisible(): void {
        if (document.visibilityState !== 'visible' || !polling) return;
        if (pollTimer !== null) clearTimeout(pollTimer);
        void pollOnce();
    }

    function begin(provider: 'google' | 'github'): void {
        if (working || waiting) return;
        const tab = window.open('about:blank', '_blank');
        try {
            if (tab) tab.opener = null;
        } catch {
        }
        void startWeb(provider, tab);
    }

    async function startWeb(provider: 'google' | 'github', tab: Window | null): Promise<void> {
        working = true;
        refusal = null;
        fallbackUrl = null;
        try {
            const started = await host.startWeb({ provider, src, consent: consentOf(news) });
            if (typeof started.url !== 'string' || !/^https:\/\//i.test(started.url)) {
                tab?.close();
                refusal = 'unavailable';
                return;
            }
            flowId = started.flow_id;
            interval = Math.max(1, Number(started.interval) || 3);
            deadline = Date.now() + Math.max(Number(started.expires_in) || 600, 1) * 1000;
            if (tab && !tab.closed) tab.location.href = started.url;
            else fallbackUrl = started.url;
            polling = true;
            waiting = true;
            pollTimer = setTimeout(() => void pollOnce(), interval * 1000);
        } catch (error) {
            tab?.close();
            refusal = refusalCodeOf(error) ?? 'unavailable';
        } finally {
            working = false;
        }
    }

    async function copyLink(): Promise<void> {
        if (!fallbackUrl) return;
        try {
            await navigator.clipboard.writeText(fallbackUrl);
            copied = true;
        } catch {
            copied = false;
        }
    }

    function stopWaiting(): void {
        stopPolling();
        fallbackUrl = null;
    }

    async function sendCode(): Promise<void> {
        if (working || emailOff || !looksLikeAddress(address)) return;
        working = true;
        refusal = null;
        try {
            const started = await host.startEmail(address.trim().toLowerCase());
            if (typeof started.flow_id !== 'string' || !started.flow_id) {
                refusal = 'unavailable';
                return;
            }
            codeFlow = started;
            viaProof = false;
            code = '';
        } catch (error) {
            const refused = refusalCodeOf(error);
            refusal = refused ?? 'unavailable';
            emailOff = isEmailUnconfigured(refused);
        } finally {
            working = false;
        }
    }

    async function useCode(): Promise<void> {
        const id = codeFlow?.flow_id;
        if (working || !id || !looksLikeCode(code)) return;
        working = true;
        refusal = null;
        try {
            const session = await (viaProof
                ? host.verifyMailbox(id, code.trim(), { src })
                : host.verifyEmail(id, code.trim(), { consent: consentOf(news), src }));
            finish(session);
        } catch (error) {
            const refused = refusalCodeOf(error);
            refusal = refused ?? 'unavailable';
            if (stepAfterRefusal(refused) === 'address') startOver();
        } finally {
            working = false;
        }
    }

    function startOver(): void {
        codeFlow = null;
        viaProof = false;
        code = '';
    }

    onMount(() => {
        document.addEventListener('visibilitychange', onVisible);
    });
    onDestroy(() => {
        stopPolling();
        document.removeEventListener('visibilitychange', onVisible);
    });
</script>

<ModalShell {title} onCancel={() => close(null)}>
    <div class="signin" data-signin-modal>
        {#if src === 'revoked'}
            <p class="signin__note" role="status" data-signin-revoked>{t('account.refusal.revoked')}</p>
        {/if}
        <p class="signin__lead">{t('account.modal.unlocks')}</p>

        {#if codeFlow}
            {#if viaProof}
                <p class="signin__note" role="status">{t('skill.signin.google.proof')}</p>
            {/if}
            <p class="signin__note" role="status">
                {t('skill.signin.email.sent', {
                    destination: codeFlow.destination,
                    minutes: minutesOf(typeof codeFlow.expires_in === 'number' ? codeFlow.expires_in : 0),
                })}
            </p>
            <Field
                id="signin-code"
                label={t('skill.signin.email.code.label')}
                inputmode="numeric"
                autocomplete="one-time-code"
                bind:value={code}
                disabled={working}
                data-signin-code
            />
            <div class="signin__row">
                <Button disabled={working} onclick={startOver}>
                    {t('skill.signin.email.restart')}
                </Button>
                <Button
                    variant="confirm"
                    disabled={working || !looksLikeCode(code)}
                    onclick={() => void useCode()}
                    data-signin-use-code
                >
                    {working ? t('skill.signin.email.checking') : t('skill.signin.email.submit')}
                </Button>
            </div>
        {:else}
            <div class="signin__providers">
                <Button disabled={working || waiting} onclick={() => begin('google')} data-signin-provider="google">
                    <span class="signin__icon"><Icon name="google" fill="solid" size={16} /></span>{t('account.modal.google')}
                </Button>
                <Button disabled={working || waiting} onclick={() => begin('github')} data-signin-provider="github">
                    <span class="signin__icon"><Icon name="github" fill="solid" size={16} /></span>{t('account.modal.github')}
                </Button>
            </div>

            {#if waiting}
                <p class="signin__note" role="status" data-signin-waiting>{t('account.modal.waiting')}</p>
                {#if fallbackUrl}
                    <p class="signin__note">{t('account.modal.link_blocked')}</p>
                    <div class="signin__row">
                        <Button href={fallbackUrl} {...NEW_TAB} data-signin-link>{t('account.modal.open_link')}</Button>
                        <Button onclick={() => void copyLink()}>
                            {copied ? t('account.modal.copied') : t('account.modal.copy_link')}
                        </Button>
                    </div>
                {/if}
                <Button onclick={stopWaiting}>{t('account.modal.stop_waiting')}</Button>
            {/if}

            <div class="signin__or" aria-hidden="true"><span>{t('account.modal.or')}</span></div>

            <Field
                id="signin-email"
                label={t('account.modal.email_label')}
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder={t('skill.signin.email.address.placeholder')}
                bind:value={address}
                disabled={working || emailOff}
                onkeydown={(event) => { if (event.key === 'Enter') void sendCode(); }}
                data-signin-email
            />
            <div class="signin__row signin__row--end">
                <Button
                    variant="confirm"
                    disabled={working || emailOff || !looksLikeAddress(address)}
                    onclick={() => void sendCode()}
                    data-signin-continue
                >
                    {t('account.modal.continue')}
                </Button>
            </div>
        {/if}

        {#if refusalSentence}
            <p class="signin__note signin__note--out" role="status">{refusalSentence}</p>
        {/if}

        <p class="signin__fine">
            {t('account.modal.consent.lead')}<a href={TERMS_URL} target="_blank" rel="noopener noreferrer">{t('account.modal.consent.terms')}</a>{t('account.modal.consent.and')}<a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer">{t('account.modal.consent.privacy')}</a>{t('account.modal.consent.end')}
        </p>
        <Check label={t('account.modal.news')} checked={news} onToggle={(next) => (news = next)} data-signin-news="" />
    </div>

    {#snippet footer()}
        <Button onclick={() => close(null)} data-signin-cancel>
            {t('account.modal.cancel')}
        </Button>
    {/snippet}
</ModalShell>

<style>
    .signin {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .signin__lead,
    .signin__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .signin__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
    }

    .signin :global(.oc-check) {
        align-self: flex-start;
    }

    .signin__providers {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .signin__providers :global([data-btn]) {
        gap: 8px;
    }

    .signin__icon {
        display: inline-flex;
        flex: 0 0 16px;
        width: 16px;
        height: 16px;
    }

    .signin__row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
    }

    .signin__row--end {
        justify-content: flex-end;
    }

    .signin :global([data-signin-code]) {
        font-family: var(--font-mono);
        font-size: 18px;
        letter-spacing: 0.18em;
    }

    .signin__or {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .signin__or::before,
    .signin__or::after {
        content: '';
        flex: 1;
        height: 1px;
        background: var(--oc-text-secondary);
        opacity: 0.35;
    }

    .signin__fine {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.45;
    }

    .signin__fine a {
        color: var(--oc-cyan);
    }
</style>
