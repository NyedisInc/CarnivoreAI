<!-- name must not be empty -->
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Card from '../base/Card.svelte';
    import Field from '../base/Field.svelte';
    import Select from '../base/Select.svelte';
    import State from '../base/State.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { LedgerHost } from './ledger-host';
    import { LEDGER_KEYS } from './ledger-model';
    import AccountPathFold from './AccountPathFold.svelte';
    import {
        accountBody,
        draftRefusal,
        pathDefaultFor,
        refusalText,
        slugFromName,
        type ProviderKind,
    } from './accounts-model';

    interface Props {
        host: LedgerHost;
        taken: readonly string[] | null;
        /* the empty state */
        startOpen?: boolean;
        onChanged: () => void | Promise<void>;
        open?: boolean;
        t?: Translate;
    }

    let {
        host,
        taken,
        startOpen = false,
        onChanged,
        open = $bindable(false),
        t = reactiveT,
    }: Props = $props();

    let seeded = false;

    $effect(() => {
        const wanted = startOpen;
        if (wanted === seeded) return;
        seeded = wanted;
        open = wanted;
    });

    let name = $state('');
    let provider = $state<ProviderKind>('claude');
    let path = $state(pathDefaultFor('claude'));
    let advanced = $state(false);
    let busy = $state(false);
    let refusal = $state<string | null>(null);

    const id = $derived(slugFromName(name));

    function chooseProvider(value: string): void {
        provider = value === 'codex' ? 'codex' : value === 'antigravity' && host.captureAgyLogin ? 'antigravity' : 'claude';
        path = pathDefaultFor(provider);
        refusal = null;
    }

    async function capture(): Promise<void> {
        if (busy || !host.captureAgyLogin) return;
        busy = true;
        refusal = null;
        try {
            await host.captureAgyLogin();
            await onChanged();
        } catch (error) {
            refusal = t(LEDGER_KEYS.editorFailed, { reason: refusalText(error, t) });
        } finally {
            busy = false;
        }
    }

    async function submit(): Promise<void> {
        if (busy) return;
        const draft = { name, provider, path, managed: !advanced, color: null };
        const refused = draftRefusal(draft, taken, t);
        if (refused) {
            refusal = refused;
            return;
        }
        busy = true;
        refusal = null;
        try {
            await host.saveAccount(slugFromName(name), accountBody(draft));
            name = '';
            path = pathDefaultFor(provider);
            await onChanged();
        } catch (error) {
            refusal = t(LEDGER_KEYS.editorFailed, { reason: refusalText(error, t) });
        } finally {
            busy = false;
        }
    }
</script>


<Card id="ledger-add-panel" data-ledger="editor" hidden={!open} foldable bind:open title={t(LEDGER_KEYS.editorSummary)} headingLevel={2}>
    {#snippet children()}
        <div class="ledger-editor__form">
            {#if provider !== 'antigravity'}
            <Field
                id="ledger-account-name"
                label={t(LEDGER_KEYS.editorNameLabel)}
                autocomplete="off"
                spellcheck={false}
                disabled={busy}
                placeholder={t(LEDGER_KEYS.editorNamePlaceholder)}
                bind:value={name}
                oninput={() => {
                    refusal = null;
                }}
            />
            {/if}

            <Select
                id="ledger-account-provider"
                label={t(LEDGER_KEYS.editorProviderLabel)}
                disabled={busy}
                value={provider}
                options={[
                    { value: 'claude', label: t(LEDGER_KEYS.editorProviderClaude) },
                    { value: 'codex', label: t(LEDGER_KEYS.editorProviderCodex) },
                    ...(host.captureAgyLogin
                        ? [{ value: 'antigravity', label: t(LEDGER_KEYS.editorProviderAntigravity) }]
                        : []),
                ]}
                onchange={(event) => chooseProvider((event.currentTarget as HTMLSelectElement).value)}
            />

            {#if provider !== 'antigravity'}
            
            <Field
                id="ledger-account-id"
                label={t(LEDGER_KEYS.editorIdLabel)}
                readonly
                tabindex={-1}
                value={id}
            />
            {/if}
        </div>

        {#if provider === 'antigravity'}
            
            <p class="ledger-editor__help" data-ledger="agy-capture-help">{t(LEDGER_KEYS.agyCaptureHelp)}</p>
        {:else}
        <p class="ledger-editor__help">{t(LEDGER_KEYS.editorManagedHelp)}</p>
        <p class="ledger-editor__help">{t(LEDGER_KEYS.editorIdHelp)}</p>

        
        <AccountPathFold bind:open={advanced} bind:path {provider} {busy} {t} />
        {/if}

        {#if refusal}
            <State kind="error" inline role="status" data-ledger="editor-refusal" title={refusal} />
        {/if}
    {/snippet}
    {#snippet foot()}
        {#if provider === 'antigravity'}
            <Button variant="confirm" data-ledger="agy-capture" disabled={busy} onclick={() => void capture()}>
                {busy ? t(LEDGER_KEYS.agyCapturing) : t(LEDGER_KEYS.agyCaptureSubmit)}
            </Button>
        {:else}
            <Button variant="confirm" data-ledger="editor-submit" disabled={busy} onclick={() => void submit()}>
                {busy ? t(LEDGER_KEYS.editorSubmitting) : t(LEDGER_KEYS.editorSubmit)}
            </Button>
        {/if}
    {/snippet}
</Card>

<style>
    .ledger-editor__form {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2) var(--oc-space-3);
    }

    .ledger-editor__form > :global(.oc-form-field) {
        flex: 1 1 160px;
        min-width: 0;
    }

    .ledger-editor__help {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    @media (max-width: 1023px) {
        .ledger-editor__form > :global(.oc-form-field) {
            flex: 1 1 100%;
        }
    }
</style>
