
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Card from '../base/Card.svelte';
    import Field from '../base/Field.svelte';
    import State from '../base/State.svelte';
    import Tag from '../base/Tag.svelte';
    import type { TagTone } from '../base/classes';
    import SwitchAccountButton from '../account-switch/SwitchAccountButton.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import LedgerRowSwatch from './LedgerRowSwatch.svelte';
    import LedgerRowActions from './LedgerRowActions.svelte';
    import LedgerRowEditor from './LedgerRowEditor.svelte';
    import LedgerUsageCell from './LedgerUsageCell.svelte';
    import LedgerSessions from './LedgerSessions.svelte';
    import type { ProviderSession } from './ledger-sessions';
    import type { AccountEdit, StoredAccount } from './accounts-model';
    import {
        LEDGER_KEYS,
        credentialLabel,
        credentialTone,
        isBuiltInLogin,
        formatAge,
        formatLoginCountdown,
        loginExpiryTone,
        pokeFailure,
        type LedgerAccount,
    } from './ledger-model';

    interface Props {
        accounts: readonly LedgerAccount[];
        now: number;
        t: Translate;
        onRemove?: (account: LedgerAccount) => void;
        removingId?: string | null;
        onLogin?: (account: LedgerAccount) => void;
        loginId?: string | null;
        onEdit?: (account: LedgerAccount, edit: AccountEdit) => Promise<boolean>;
        editingId?: string | null;
        /* the built-in login */
        onRename?: (account: LedgerAccount, label: string) => Promise<boolean>;
        stored?: (id: string) => StoredAccount | null;
        rowNotices?: Readonly<Record<string, string>>;
        targetId?: string | null;
        sessionsFor?: (id: string) => readonly ProviderSession[];
        onOpenSession?: (row: ProviderSession) => void;
    }

    const {
        accounts,
        now,
        t,
        onRemove,
        removingId = null,
        onLogin,
        loginId = null,
        onEdit,
        editingId = null,
        onRename,
        stored = () => null,
        rowNotices = {},
        targetId = null,
        sessionsFor,
        onOpenSession,
    }: Props = $props();

    let confirmingId = $state<string | null>(null);

    let openEditorId = $state<string | null>(null);

    let renameDraft = $state<string | null>(null);

    async function saveRename(account: LedgerAccount): Promise<void> {
        const landed = await onRename?.(account, renameDraft ?? '');
        if (landed === true) renameDraft = null;
    }

    function openEditor(id: string | null): void {
        openEditorId = openEditorId === id ? null : id;
        confirmingId = null;
    }

    async function saveEditor(account: LedgerAccount, edit: AccountEdit): Promise<void> {
        const landed = await onEdit?.(account, edit);
        if (landed === true) openEditorId = null;
    }

    function tagToneFor(tone: string): TagTone {
        return tone === 'ok' ? 'ok' : tone === 'warn' ? 'warn' : tone === 'high' ? 'danger' : 'neutral';
    }

    function shown(value: string | null | undefined): string {
        return value ?? t(LEDGER_KEYS.valueUnknown);
    }
</script>

<ul class="ledger-grid" aria-label={t(LEDGER_KEYS.accountsLabel)}>
    {#each accounts as account, index (account.id ?? index)}
        {@const tone = credentialTone(account.credential_state)}
        {@const mark = providerMark(account.provider, 14)}
        {@const loginLeft = formatLoginCountdown(account.login_expires_at, now, t)}
        {@const pokeText = pokeFailure(account, t)}
        {@const editing = openEditorId === account.id}
        {@const notice = editing ? null : (rowNotices[account.id] ?? null)}
        {@const ownError = account.error && account.error !== account.poke?.error ? account.error : null}
        {@const edit = onEdit && stored(account.id) ? () => openEditor(account.id) : undefined}
        {@const editorRow = editing && onEdit ? stored(account.id) : null}
        <li class="ledger-cell" class:ledger-cell--wide={editing}>
            <Card
                data-ledger="row"
                data-account-id={account.id}
                data-tone={tone}
                data-landed={targetId !== null && account.id === targetId ? '' : undefined}
                title={shown(account.name)}
                headingLevel={2}
            >
                {#snippet lead()}
                    
                    <LedgerRowSwatch
                        color={account.color ?? null}
                        name={account.name ?? account.id}
                        busy={editingId === account.id}
                        {editing}
                        {t}
                        onEdit={edit}
                    />
                    <span data-ledger="provider-mark" data-agent-family={mark.key} role="img" aria-label={mark.label} title={mark.label}>{@html mark.svg}</span>
                {/snippet}
                {#snippet actions()}
                    
                    <Tag tone={tagToneFor(tone)} data-ledger="chip" data-tone={tone}>{credentialLabel(account.credential_state, t)}</Tag>
                {/snippet}
                {#snippet children()}
                    <div class="ledger-card__cols" class:ledger-card__cols--editing={editing}>
                        <div class="ledger-card__readout">
                            
                            <div class="ledger-card__byline">
                                <span class="ledger-identity" class:ledger-unread={account.identity == null}
                                    >{shown(account.identity)}</span
                                >
                                {#if loginLeft}
                                    <span
                                        class="ledger-expiry"
                                        data-tone={loginExpiryTone(account.login_expires_at, now) ?? ''}
                                        >{loginLeft}</span
                                    >
                                {/if}
                            </div>

                            
                            {#if notice}
                                <State kind="error" inline role="status" data-ledger="error" title={notice} />
                            {/if}
                            {#if ownError}
                                <State kind="error" inline role="alert" data-ledger="error"
                                    title={t(LEDGER_KEYS.accountError, { detail: ownError })} />
                            {/if}
                            {#if pokeText}
                                <State kind="error" inline role="alert" data-ledger="error" title={pokeText} />
                            {/if}

                            <LedgerUsageCell windows={account.windows ?? []} {now} {t} hero />

                            {#if sessionsFor && onOpenSession}
                                <LedgerSessions rows={sessionsFor(account.id)} {t} onOpen={onOpenSession} />
                            {/if}
                        </div>

                        {#if editorRow}
                            <LedgerRowEditor
                                stored={editorRow}
                                label={account.name ?? account.id}
                                busy={editingId === account.id}
                                refusal={rowNotices[account.id] ?? null}
                                {t}
                                onSave={(value) => void saveEditor(account, value)}
                                onCancel={() => openEditor(null)}
                            />
                        {/if}
                    </div>
                {/snippet}
                {#snippet foot()}
                    
                    <ul class="ledger-card__tags">
                        <li><Tag>{shown(account.plan)}</Tag></li>
                        {#if isBuiltInLogin(account)}
                            <li><Tag>{t(LEDGER_KEYS.builtInLogin)}</Tag></li>
                        {:else if account.managed === true}
                            <li><Tag>{t(LEDGER_KEYS.tagManaged)}</Tag></li>
                        {/if}
                    </ul>
                    <span class="ledger-card__fetched">
                        {account.fetched_at == null
                            ? formatAge(account.fetched_at, now, t)
                            : t(LEDGER_KEYS.fetched, { age: formatAge(account.fetched_at, now, t) })}
                    </span>
                    
                    <SwitchAccountButton
                        account={{
                            id: account.id,
                            name: account.name ?? account.id,
                            provider: account.provider,
                            setup_complete: account.setup_complete,
                        }}
                        onLogin={onLogin ? () => onLogin(account) : undefined}
                    />

                    {#if isBuiltInLogin(account)}
                        {#if onRename && renameDraft === null}
                            <div class="ledger-card__actions" data-ledger="actions" role="group" aria-label={t(LEDGER_KEYS.columnActions)}>
                                <Button
                                    variant="quiet"
                                    data-ledger="rename-start"
                                    onclick={() => {
                                        renameDraft = account.name ?? '';
                                    }}>{t(LEDGER_KEYS.builtInRename)}</Button
                                >
                            </div>
                        {/if}
                        {#if onRename && renameDraft !== null}
                            <form
                                class="ledger-card__actions"
                                data-ledger="rename"
                                onsubmit={(event) => {
                                    event.preventDefault();
                                    void saveRename(account);
                                }}
                            >
                                <Field
                                    data-ledger="rename-input"
                                    aria-label={t(LEDGER_KEYS.builtInRenameLabel)}
                                    placeholder={t(LEDGER_KEYS.builtInRenameLabel)}
                                    autocomplete="off"
                                    spellcheck={false}
                                    maxlength={40}
                                    disabled={editingId === account.id}
                                    bind:value={renameDraft}
                                />
                                <Button
                                    variant="confirm"
                                    type="submit"
                                    data-ledger="rename-save"
                                    disabled={editingId === account.id}
                                    >{t(LEDGER_KEYS.builtInRenameSave)}</Button
                                >
                                <Button
                                    data-ledger="rename-cancel"
                                    onclick={() => {
                                        renameDraft = null;
                                    }}>{t(LEDGER_KEYS.builtInRenameCancel)}</Button
                                >
                            </form>
                        {/if}
                    {:else if onRemove}
                        <div class="ledger-card__actions" data-ledger="actions" role="group" aria-label={t(LEDGER_KEYS.columnActions)}>
                            <LedgerRowActions
                                {account}
                                {t}
                                {onRemove}
                                {onLogin}
                                onEdit={edit}
                                {editing}
                                confirming={confirmingId === account.id}
                                onConfirming={(armed) => {
                                    confirmingId = armed ? account.id : null;
                                }}
                                removing={removingId === account.id}
                                loggingIn={loginId === account.id}
                            />
                        </div>
                    {/if}
                {/snippet}
            </Card>
        </li>
    {/each}
</ul>

<style>
    .ledger-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
        gap: var(--oc-space-4);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .ledger-cell {
        display: flex;
        min-width: 0;
    }

    .ledger-cell > :global(.oc-card) {
        width: 100%;
    }

    .ledger-cell--wide {
        grid-column: 1 / -1;
    }

    .ledger-card__cols,
    .ledger-card__readout {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        min-width: 0;
    }

    @media (min-width: 1024px) {
        .ledger-card__cols--editing {
            display: grid;
            grid-template-columns: minmax(0, 400px) minmax(0, 1fr);
            gap: var(--oc-space-4);
        }
    }

    [data-ledger='provider-mark'] {
        display: inline-flex;
        flex: none;
    }

    .ledger-card__byline {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: var(--oc-space-0-5) var(--oc-space-3);
        min-width: 0;
    }

    .ledger-identity {
        min-width: 0;
        overflow: hidden;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .ledger-unread {
        color: var(--oc-text-muted);
    }

    .ledger-card__tags {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-1-5);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .ledger-card__fetched {
        margin-left: auto;
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-micro);
        white-space: nowrap;
    }

    .ledger-expiry {
        font-size: var(--oc-fs-hint);
        color: var(--oc-text-muted);
    }

    .ledger-expiry[data-tone='warn'] {
        color: var(--oc-yellow);
    }

    .ledger-expiry[data-tone='high'] {
        color: var(--oc-coral);
    }

    .ledger-card__actions {
        display: flex;
        flex: 1 1 100%;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .ledger-card__actions :global(.oc-form-field),
    .ledger-card__actions :global([data-field]) {
        flex: 1 1 160px;
        min-width: 0;
    }

    @media (max-width: 1023px) {
        .ledger-grid {
            gap: var(--oc-space-3);
        }
    }
</style>
