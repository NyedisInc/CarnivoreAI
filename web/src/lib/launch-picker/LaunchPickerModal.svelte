<!-- active account -->
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import { createLaunchProfilesApi, errorText, type AccountOption, type LaunchProfilesApi, type ModelOption, type ProfileRow } from '../launch-profiles-page/api';
    import type { RestartAccounts } from './account-types';
    import type { AccountAnswer } from './account-model';
    import LaunchChoice from './LaunchChoice.svelte';
    import { answerFor, farRows, initialSelection, isValidModelId, rowsFromProfiles, type PickerRow } from './picker-model';

    interface Props {
        title: string;
        t: Translate;
        preselect?: string | null;
        projectDefault?: string | null;
        harness?: string | null;
        onlyHarnesses?: readonly string[] | null;
        onlyIds?: readonly string[] | null;
        api?: LaunchProfilesApi;
        lastModel?: string;
        accounts?: boolean;
        remote?: { key: string; label: string } | null;
        goLabel?: string | null;
        close: (value: { profileId: string; profileLabel: string; model: string | null; account: AccountAnswer | null; farLauncher?: boolean } | null) => void;
    }
    const { title, t, preselect = null, projectDefault = null, harness = null, onlyHarnesses = null, onlyIds = null, api: injected, lastModel = '', accounts: withAccounts = true, remote = null, goLabel = null, close }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: LaunchProfilesApi = injected ?? createLaunchProfilesApi();

    let rows = $state<PickerRow[]>([]);
    let value = $state('');
    let reason = $state<string>('none');
    let loading = $state(true);
    let failure = $state('');
    let model = $state('');
    let suggestions = $state<ModelOption[]>([]);
    let launchAccounts = $state<RestartAccounts | null>(null);
    let account = $state<AccountAnswer | null>(null);
    let accountName = $state<string | null>(null);
    let farListed = $state(false);

    const picked = $derived(rows.find((r) => r.value === value));
    const answer = $derived(answerFor(picked, model));
    const canGo = $derived(!!picked && (picked.modelMode !== 'ask' || isValidModelId(model.trim())));

    onMount(() => {
        void (async () => {
            if (remote) {
                const far = await api.computerLaunchers(remote.key).catch((): null => null);
                farListed = far?.status === 'ok' && far.launchers.length > 0;
                rows = farRows(farListed && far?.status === 'ok' ? far.launchers : null, far?.status === 'ssh' ? far.families : undefined);
                const start = initialSelection(rows, { harness });
                value = start.value; reason = start.reason;
                loading = false;
                return;
            }
            try {
                const [list, accounts, launchable] = await Promise.all([
                    api.list(), api.accounts().catch((): AccountOption[] => []),
                    withAccounts ? api.launchAccounts().catch((err: unknown): null => { console.warn('LaunchPicker: the account list could not be read:', errorText(err)); return null; }) : Promise.resolve(null),
                ]);
                launchAccounts = launchable;
                const all = rowsFromProfiles(list.profiles as ProfileRow[], accounts, {
                    followActive: t('launch_profiles.list.follow'), modelDefault: t('launch_picker.model_default'), modelAsk: t('launch_picker.model_ask'),
                });
                rows = all.filter((r) => (!onlyHarnesses || onlyHarnesses.includes(r.harness)) && (!onlyIds || onlyIds.includes(r.value)));
                const start = initialSelection(rows, { preselect, projectDefault, harness });
                value = start.value; reason = start.reason;
                model = lastModel;
            } catch (err) { failure = errorText(err); }
            loading = false;
        })();
    });

    $effect(() => {
        const row = picked;
        suggestions = [];
        if (!row || row.modelMode !== 'ask' || !row.connectionId) return;
        let live = true;
        api.models(row.connectionId).then((m) => { if (live) suggestions = m; }).catch(() => undefined);
        return () => { live = false; };
    });

    function go(): void {
        if (canGo && answer && picked) close({ ...answer, profileLabel: picked.label, account, ...(remote ? { farLauncher: farListed } : {}) });
    }
</script>

<ModalShell {title} onCancel={() => close(null)}>
    <div class="lpm" data-launch-picker-modal>
        {#if loading}
            <p class="lpm-note">{t('launch_picker.loading')}</p>
        {:else if failure}
            <p class="lpm-error" role="alert">{t('launch_picker.failed', { reason: failure })}</p>
        {:else if rows.length === 0}
            <p class="lpm-note">{t('launch_picker.empty')}</p>
        {:else}
            {#if remote}<p class="lpm-note" data-lpm-remote>{t(farListed ? 'launch_picker.remote.listed' : 'launch_picker.remote.families', { computer: remote.label })}</p>{/if}
            <LaunchChoice {rows} bind:value accounts={remote ? null : launchAccounts} followWords={t('launch_profiles.list.follow')} bind:account bind:accountName {t} />
            {#if picked && remote}
                <p class="lpm-names" data-lpm-names>{t('launch_picker.remote.will_use', { label: picked.label, computer: remote.label })}</p>
            {:else if picked}
                <p class="lpm-names" data-lpm-names>
                    {t('launch_picker.will_use', { label: picked.label, account: accountName ?? picked.account, model: picked.model })}
                    <span class="lpm-why">{t(`launch_picker.why.${reason}`)}</span>
                </p>
                {#if picked.modelMode === 'ask'}
                    <label class="lpm-field" for="lpm-model">{t('launch_picker.model_label')}</label>
                    <input id="lpm-model" class="modal-input oc-focus-host" type="text" list="lpm-models" spellcheck="false" autocomplete="off" bind:value={model} placeholder={t('launch_picker.model_placeholder')} />
                    <datalist id="lpm-models">{#each suggestions as m (m.id)}<option value={m.id}>{m.label}</option>{/each}</datalist>
                {/if}
            {/if}
        {/if}
    </div>
    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" onclick={() => close(null)}>{t('launch_picker.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-confirm" disabled={!canGo} data-lpm-go onclick={go}>{goLabel ?? t('launch_picker.go')}</button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .lpm { display: flex; flex-direction: column; gap: 8px; min-width: 0; max-height: 60vh; overflow-y: auto; font-family: var(--font-mono); }
    .lpm-note, .lpm-names { margin: 0; color: var(--oc-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
    .lpm-names { padding: 6px 10px; border-left: 2px solid var(--oc-orange); background: var(--oc-ground-field); color: var(--oc-text-primary); }
    .lpm-why { display: block; color: var(--oc-text-muted); font-size: 11px; }
    .lpm-error { margin: 0; padding: 6px 8px; border-left: 2px solid var(--oc-coral); background: var(--oc-ground-field); color: var(--oc-text-primary); font-size: 12px; overflow-wrap: anywhere; }
    .lpm-field { color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
  }
</style>
