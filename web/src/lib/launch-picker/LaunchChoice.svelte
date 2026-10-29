
<script lang="ts">
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { RestartAccounts } from './account-types';
    import { answerOf, appliesTo, startAccountId, type AccountAnswer } from './account-model';
    import LaunchAccountChoice from './LaunchAccountChoice.svelte';
    import LaunchProfileDropdown from './LaunchProfileDropdown.svelte';
    import type { PickerRow } from './picker-model';

    interface Props {
        rows: readonly PickerRow[];
        value?: string;
        accounts?: RestartAccounts | null;
        followWords?: string;
        compact?: boolean;
        label?: string;
        account?: AccountAnswer | null;
        accountName?: string | null;
        onchange?: (value: string) => void;
        t?: Translate;
    }
    let { rows, value = $bindable(''), accounts = null, followWords = '', compact = false, label = '', account = $bindable(null), accountName = $bindable(null), onchange, t = appT }: Props = $props();

    let expanded = $state(false);
    let accountId = $state('');
    let pinned = $state(false);

    $effect(() => {
        if (!accounts) return;
        expanded = accounts.pinned === true;
        pinned = accounts.pinned === true;
        accountId = startAccountId(accounts);
    });

    const show = $derived(appliesTo(rows.find((r) => r.value === value), accounts));
    $effect(() => {
        account = answerOf(show, expanded, accountId, pinned);
        const chosen = expanded ? accounts?.options.find((o) => o.id === accountId) : accounts?.options.find((o) => o.id === accounts?.selected_id);
        accountName = show ? (chosen?.name ?? null) : null;
    });
</script>

<div class="lch" data-launch-choice>
    <LaunchProfileDropdown {rows} bind:value {compact} {label} {onchange} {t} />
    {#if show && accounts}
        <LaunchAccountChoice answer={accounts} bind:expanded bind:accountId bind:pinned {followWords} {t} />
    {/if}
</div>

<style>
    @layer components {
        .lch { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    }
</style>
