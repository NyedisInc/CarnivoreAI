<!-- hidden -->
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import State from '../base/State.svelte';
    import type { Translate } from '../sessions/types';
    import ColorSwatches from './ColorSwatches.svelte';
    import { LEDGER_KEYS } from './ledger-model';
    import {
        pathLabelKey,
        type AccountEdit,
        type ProviderKind,
        type StoredAccount,
    } from './accounts-model';

    interface Props {
        stored: StoredAccount;
        label: string;
        onSave: (edit: AccountEdit) => void;
        onCancel: () => void;
        busy: boolean;
        refusal: string | null;
        t: Translate;
    }

    const { stored, label, onSave, onCancel, busy, refusal, t }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(typeof stored.name === 'string' ? stored.name : '');

    // svelte-ignore state_referenced_locally
    let shortName = $state(typeof stored.short_name === 'string' ? stored.short_name : '');

    // svelte-ignore state_referenced_locally
    let color = $state<string | null>(stored.color ?? null);

    const provider = $derived<ProviderKind>(stored.provider === 'codex' ? 'codex' : 'claude');

    const path = $derived(
        (provider === 'codex' ? stored.codex_home : stored.claude_config_dir) ?? '',
    );

    const managed = $derived(stored.managed === true);
</script>

<div class="ledger-edit" data-ledger="edit">
    <p class="oc-label ledger-edit__title">{t(LEDGER_KEYS.editTitle, { name: label })}</p>

    <div class="ledger-edit__form">
        <Field
            id="ledger-edit-name"
            label={t(LEDGER_KEYS.editorNameLabel)}
            autocomplete="off"
            spellcheck={false}
            disabled={busy}
            bind:value={name}
        />
        <Field
            id="ledger-edit-short-name"
            label={t(LEDGER_KEYS.editShortNameLabel)}
            autocomplete="off"
            spellcheck={false}
            maxlength={32}
            placeholder={t(LEDGER_KEYS.editShortNamePlaceholder)}
            disabled={busy}
            bind:value={shortName}
        />
    </div>

    
    <dl class="ledger-edit__facts">
        <div class="ledger-edit__fact">
            <dt class="oc-label">{t(LEDGER_KEYS.editorIdLabel)}</dt>
            <dd class="ledger-edit__value ledger-edit__value--mono">{stored.id}</dd>
        </div>
        <div class="ledger-edit__fact">
            <dt class="oc-label">{t(LEDGER_KEYS.editorProviderLabel)}</dt>
            <dd class="ledger-edit__value">{provider}</dd>
        </div>
        <div class="ledger-edit__fact">
            <dt class="oc-label">{t(LEDGER_KEYS.editManagedLabel)}</dt>
            <dd class="ledger-edit__value">
                {managed ? t(LEDGER_KEYS.editManagedYes) : t(LEDGER_KEYS.editManagedNo)}
            </dd>
        </div>
        <div class="ledger-edit__fact ledger-edit__fact--wide">
            <dt class="oc-label">{t(pathLabelKey(provider))}</dt>
            <dd
                class="ledger-edit__value ledger-edit__value--mono"
            >
                {path === '' ? t(LEDGER_KEYS.valueUnknown) : path}
            </dd>
        </div>
    </dl>

    
    <div class="ledger-edit__colors">
        <span class="oc-label" id="ledger-edit-color-label">
            {t(LEDGER_KEYS.colorLabel)}
        </span>
        <ColorSwatches
            value={color}
            disabled={busy}
            {t}
            onPick={(hex) => {
                color = hex;
            }}
        />
    </div>

    <p class="ledger-edit__help">{t(LEDGER_KEYS.editImmutableHelp)}</p>

    {#if refusal}
        <State kind="error" inline role="status" data-ledger="edit-refusal" title={refusal} />
    {/if}

    <div class="ledger-edit__actions">
        <Button
            variant="confirm"
            data-ledger="edit-save"
            disabled={busy}
            onclick={() => onSave({ name, color, short_name: shortName })}
        >
            {busy ? t(LEDGER_KEYS.editSaving) : t(LEDGER_KEYS.editSave)}
        </Button>
        <Button data-ledger="edit-cancel" disabled={busy} onclick={onCancel}>
            {t(LEDGER_KEYS.editCancel)}
        </Button>
    </div>
</div>

<style>
    .ledger-edit {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        min-width: 0;
        white-space: normal;
    }

    .ledger-edit__title {
        margin: 0;
        color: var(--oc-orange);
    }

    .ledger-edit__form {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2) var(--oc-space-3);
    }

    .ledger-edit__form > :global(.oc-form-field) {
        flex: 1 1 150px;
        min-width: 0;
    }

    .ledger-edit__facts {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--oc-space-2) var(--oc-space-3);
        margin: 0;
    }

    .ledger-edit__fact {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-0-5);
        min-width: 0;
    }

    .ledger-edit__fact--wide {
        grid-column: 1 / -1;
    }

    .ledger-edit__value {
        margin: 0;
        font-size: var(--oc-fs-body);
        color: var(--oc-text-primary);
        overflow-wrap: anywhere;
    }

    .ledger-edit__value--mono {
        font-family: var(--font-mono);
    }

    .ledger-edit__colors {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
    }

    .ledger-edit__help {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .ledger-edit__actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
    }

    @media (max-width: 1023px) {
        .ledger-edit__form > :global(.oc-form-field) {
            flex: 1 1 100%;
        }

        .ledger-edit__facts {
            grid-template-columns: minmax(0, 1fr);
        }
    }
</style>
