
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import State from '../base/State.svelte';
    import { onDestroy } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import './phone-link/phone-link.css';
    import './phone-link/custom-domain.css';
    import { ApiError } from '../../opscenter/api/auth.svelte';
    import { resourcePush } from '../resource-push/boot';
    import { errorText } from './panel-kit/error-text';
    import { copyText } from './mcp-panel/api';
    import CopyField from './CopyField.svelte';
    import {
        EMPTY,
        agentPrompt,
        checkMessage,
        deleteCustomDomain,
        errorKey,
        getCustomDomain,
        ledOf,
        putCustomDomain,
        refusalKey,
        stateKey,
        type CustomDomain,
        type Fetcher,
    } from './phone-link/custom-domain';
    import { utcMinute } from './phone-link/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        part?: 'all' | 'main' | 'lifecycle';
    }
    const { t = reactiveT, fetcher, part = 'all' }: Props = $props();

    const FALLBACK_MS = 10000;

    let view = $state<CustomDomain>(EMPTY);
    let draft = $state('');
    let busy = $state(false);
    let problem = $state('');
    let copied = $state('');

    async function load(): Promise<void> {
        try {
            view = await getCustomDomain(fetcher);
        } catch (error) {
            if (error instanceof ApiError && error.status === 403) return;
            problem = errorText(error);
        }
    }
    void load();
    const stopPush = resourcePush().pushOrPoll(() => void load(), FALLBACK_MS, ['custom_domain']);
    onDestroy(stopPush);

    const failure = (error: unknown): string => {
        const key = refusalKey(error);
        return key ? t(key) : errorText(error);
    };

    async function act(work: () => Promise<CustomDomain>): Promise<void> {
        busy = true;
        problem = '';
        try {
            view = { ...EMPTY, ...(await work()) };
        } catch (error) {
            if (error instanceof ApiError && error.status === 403 && error.code === 'account_required') return;
            problem = failure(error);
        } finally {
            busy = false;
        }
    }

    const submit = () => act(() => putCustomDomain(draft, fetcher));
    let confirmingRemove = $state(false);
    const remove = () => act(() => deleteCustomDomain(fetcher));

    async function copy(which: string, text: string): Promise<void> {
        try {
            await copyText(text);
            copied = which;
            setTimeout(() => (copied = copied === which ? '' : copied), 1500);
        } catch {
            problem = t('phoneLink.customDomain.copy_failed');
        }
    }

    const bound = $derived(view.domain !== null && view.state !== 'none' && view.state !== 'released');
    const check = $derived(checkMessage(view));
    const errKey = $derived(errorKey(view.error));
    const led = $derived(ledOf(view.state));
</script>

{#snippet removeButton()}
    <div>
        {#if confirmingRemove && bound}
            <Button data-cd="remove-keep" disabled={busy} onclick={() => (confirmingRemove = false)}>{t('phoneLink.customDomain.remove_keep')}</Button>
            <Button variant="danger" data-cd="remove-sure" disabled={busy} onclick={() => { confirmingRemove = false; void remove(); }}>
                {t('phoneLink.customDomain.remove_sure')}
            </Button>
        {:else}
            <Button variant="danger" data-cd="remove" disabled={busy || !bound} onclick={() => (confirmingRemove = true)}>
                {t('phoneLink.customDomain.remove')}
            </Button>
        {/if}
    </div>
{/snippet}

{#if part === 'lifecycle'}
    <div class="cd cd--lifecycle" data-cd="lifecycle">
        {@render removeButton()}
        {#if problem}<State kind="error" inline title={problem} data-cd="problem" />{/if}
    </div>
{:else}
<section class="cd" data-cd="panel">
    <h4 class="oc-label">{t('phoneLink.customDomain.title')}</h4>
    <p class="tm__sub">{t('phoneLink.customDomain.hint')}</p>

    {#if bound}
        <p class="cd-state" data-cd="state">
            <span class="cd-led cd-led--{led}" role="img" aria-label={t(`phoneLink.customDomain.led.${led}`)} data-cd-led={led}></span>
            <span class="cd-domain" data-cd="domain">{view.domain_display ?? view.domain}</span>
            <span data-cd="state-text">{t(stateKey(view), { time: view.lockout_until ? utcMinute(view.lockout_until) : '' })}</span>
        </p>

        {#if view.target && view.domain && view.state !== 'live'}
            <p class="tm__sub">{t('phoneLink.customDomain.record.hint')}</p>
            <div class="cd-record" data-cd="record">
                {#each [['name', `${view.domain}.`], ['type', 'CNAME'], ['target', `${view.target}.`]] as [which, text] (which)}
                    <div class="cd-cell">
                        <small>{t(`phoneLink.customDomain.record.${which}`)}</small>
                        <CopyField value={text ?? ''} {t} label={t(`phoneLink.customDomain.record.${which}`)}
                            valueAttrs={{ 'data-cd': `cell-${which}` }} buttonAttrs={{ 'data-cd': `copy-${which}` }} />
                    </div>
                {/each}
            </div>
            <div>
                <Button size="sm" data-cd="copy-prompt" onclick={() => void copy('prompt', agentPrompt(view.domain ?? '', view.target ?? '', t))}>
                    {copied === 'prompt' ? t('phoneLink.customDomain.copied') : t('phoneLink.customDomain.copy_prompt')}
                </Button>
            </div>
        {/if}

        {#if check}<State kind="warn" role="status" title={t(check.key, check.params)} data-cd="check" />{/if}

        {#if view.cert}
            <dl class="pl-facts" data-cd="cert">
                <dt>{t('phoneLink.customDomain.cert')}</dt>
                <dd>{t('phoneLink.customDomain.cert.value', { issuer: view.cert.issuer, expiry: utcMinute(Date.parse(view.cert.not_after) / 1000) })}</dd>
            </dl>
        {:else if view.state === 'live'}
            <p class="tm__sub" data-cd="cert-none">{t('phoneLink.customDomain.cert.none')}</p>
        {/if}

        {#if errKey}<State kind="error" inline title={t(errKey)} data-cd="error" />{/if}

        {#if part === 'all'}{@render removeButton()}{/if}
    {:else}
        <form class="cd-form" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
            <Field bind:value={draft} disabled={busy} spellcheck={false} autocomplete="off" autocapitalize="off"
                placeholder={t('phoneLink.customDomain.placeholder')} aria-label={t('phoneLink.customDomain.field')} data-cd="input" />
            <Button type="submit" variant="confirm" data-cd="submit" disabled={busy || draft.trim() === ''}>
                {t('phoneLink.customDomain.submit')}
            </Button>
        </form>
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-cd="problem" />{/if}
</section>
{/if}
