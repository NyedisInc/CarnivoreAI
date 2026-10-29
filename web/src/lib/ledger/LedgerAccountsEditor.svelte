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
    import ColorSwatches from './ColorSwatches.svelte';
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
    let color = $state<string | null>(null);
    let busy = $state(false);
    let refusal = $state<string | null>(null);

    const id = $derived(slugFromName(name));

    function chooseProvider(value: string): void {
        provider = value === 'codex' ? 'codex' : 'claude';
        path = pathDefaultFor(provider);
        refusal = null;
    }

    async function submit(): Promise<void> {
        if (busy) return;
        const draft = { name, provider, path, managed: !advanced, color };
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
            color = null;
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

            <Select
                id="ledger-account-provider"
                label={t(LEDGER_KEYS.editorProviderLabel)}
                disabled={busy}
                value={provider}
                options={[
                    { value: 'claude', label: t(LEDGER_KEYS.editorProviderClaude) },
                    { value: 'codex', label: t(LEDGER_KEYS.editorProviderCodex) },
                ]}
                onchange={(event) => chooseProvider((event.currentTarget as HTMLSelectElement).value)}
            />

            
            <div class="ledger-editor__colors">
                <span class="oc-label" id="ledger-account-color-label">
                    {t(LEDGER_KEYS.colorLabel)}
                </span>
                <ColorSwatches
                    value={color}
                    disabled={busy}
                    {t}
                    onPick={(hex) => {
                        color = hex;
                        refusal = null;
                    }}
                />
            </div>

            
            <Field
                id="ledger-account-id"
                label={t(LEDGER_KEYS.editorIdLabel)}
                readonly
                tabindex={-1}
                value={id}
            />
        </div>

        <p class="ledger-editor__help">{t(LEDGER_KEYS.editorManagedHelp)}</p>
        <p class="ledger-editor__help">{t(LEDGER_KEYS.editorIdHelp)}</p>

        
        <AccountPathFold bind:open={advanced} bind:path {provider} {busy} {t} />

        {#if refusal}
            <State kind="error" inline role="status" data-ledger="editor-refusal" title={refusal} />
        {/if}
    {/snippet}
    {#snippet foot()}
        <Button variant="confirm" data-ledger="editor-submit" disabled={busy} onclick={() => void submit()}>
            {busy ? t(LEDGER_KEYS.editorSubmitting) : t(LEDGER_KEYS.editorSubmit)}
        </Button>
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

    .ledger-editor__colors {
        display: flex;
        flex: 2 1 240px;
        flex-direction: column;
        gap: var(--oc-space-1);
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
        .ledger-editor__form > :global(.oc-form-field),
        .ledger-editor__colors {
            flex: 1 1 100%;
        }
    }
</style>
