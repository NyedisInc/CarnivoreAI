
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import { LEDGER_KEYS, removeConfirmKey, type LedgerAccount } from './ledger-model';

    interface Props {
        account: LedgerAccount;
        t: Translate;
        onRemove?: (account: LedgerAccount) => void;
        onLogin?: (account: LedgerAccount) => void;
        onEdit?: (account: LedgerAccount) => void;
        editing: boolean;
        confirming: boolean;
        onConfirming: (armed: boolean) => void;
        removing: boolean;
        loggingIn: boolean;
    }

    const {
        account,
        t,
        onRemove,
        onLogin,
        onEdit,
        editing,
        confirming,
        onConfirming,
        removing,
        loggingIn,
    }: Props = $props();

    function loginIsUrgent(state: string | null | undefined): boolean {
        return state === 'missing' || state === 'expired';
    }
</script>

{#if confirming}
    <span class="ledger-confirm" data-ledger="confirm">
        <span class="ledger-confirm__ask"
            >{t(removeConfirmKey(account), { name: account.name ?? account.id })}</span
        >
        <span class="ledger-confirm__answers">
            <Button
                variant="danger"
                data-ledger="confirm-yes"
                disabled={removing}
                onclick={() => onRemove?.(account)}
                >{removing ? t(LEDGER_KEYS.editorRemoving) : t(LEDGER_KEYS.editorRemoveYes)}</Button
            >
            <Button
                data-ledger="confirm-no"
                disabled={removing}
                onclick={() => onConfirming(false)}>{t(LEDGER_KEYS.editorRemoveCancel)}</Button
            >
        </span>
    </span>
{:else}
    <span class="ledger-actions__pair">
        {#if onLogin}
            <Button
                variant={loginIsUrgent(account.credential_state) ? 'confirm' : 'secondary'}
                data-ledger="login"
                data-urgent={loginIsUrgent(account.credential_state) ? '' : undefined}
                disabled={loggingIn}
                onclick={() => onLogin(account)}
                >{loggingIn
                    ? t(LEDGER_KEYS.loginStarting)
                    : account.credential_state === 'ok'
                      ? t(LEDGER_KEYS.loginAgain)
                      : t(LEDGER_KEYS.loginStart)}</Button
            >
        {/if}
        
        <span class="ledger-actions__rest">
            {#if onEdit}
                <Button
                    variant="quiet"
                    data-ledger="edit-start"
                    aria-expanded={editing}
                    onclick={() => onEdit(account)}>{t(LEDGER_KEYS.editStart)}</Button
                >
            {/if}
            {#if onRemove}
                <Button
                    variant="quiet"
                    data-ledger="remove"
                    onclick={() => onConfirming(true)}>{t(LEDGER_KEYS.editorRemove)}</Button
                >
            {/if}
        </span>
    </span>
{/if}

<style>
    .ledger-actions__pair {
        display: flex;
        flex: 1 1 100%;
        align-items: center;
        gap: var(--oc-space-2);
    }

    .ledger-actions__rest {
        display: flex;
        gap: var(--oc-space-1);
        margin-left: auto;
    }

    .ledger-confirm {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
    }

    .ledger-confirm__ask {
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-body);
        line-height: 1.45;
    }

    .ledger-confirm__answers {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
    }
</style>
