<!-- the launch choice -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as appT } from '../i18n/index.svelte';
    import { createLaunchProfilesApi, type AccountOption, type LaunchProfilesApi, type ProfileRow } from '../launch-profiles-page/api';
    import type { AccountAnswer } from './account-model';
    import type { RestartAccounts } from './account-types';
    import LaunchChoice from './LaunchChoice.svelte';
    import { enrichRows, type PickerRow } from './picker-model';

    interface Props {
        rows: readonly PickerRow[];
        value?: string;
        label?: string;
        accounts?: RestartAccounts | null;
        api?: LaunchProfilesApi;
    }
    const { rows: initial, value: start = '', label = '', accounts = null, api: injected }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: LaunchProfilesApi = injected ?? createLaunchProfilesApi();
    // svelte-ignore state_referenced_locally
    let facts = $state.raw<readonly PickerRow[]>(initial);
    // svelte-ignore state_referenced_locally
    let value = $state(start);
    let account = $state.raw<AccountAnswer | null>(null);
    let allowed = $state.raw<((data: Record<string, string>) => boolean) | null>(null);
    let root: HTMLDivElement | undefined = $state();
    let seen = false;
    let loaded = $state(false);

    const shown = $derived<readonly PickerRow[]>(allowed ? facts.map((r) => ({ ...r, disabled: !allowed!(r.data) })) : facts);

    onMount(() => {
        let live = true;
        void (async () => {
            try {
                const [list, names] = await Promise.all([api.list(), api.accounts().catch((): AccountOption[] => [])]);
                if (!live) return;
                facts = enrichRows(initial, list.profiles as ProfileRow[], names, {
                    followActive: appT('launch_profiles.list.follow'), modelDefault: appT('launch_picker.model_default'), modelAsk: appT('launch_picker.model_ask'),
                });
            } catch (err) {
                console.warn('LaunchChoiceHost: profile facts unavailable, rows keep their own words', err);
            }
            if (live) loaded = true;
        })();
        return () => { live = false; };
    });

    $effect(() => {
        void value;
        void account?.accountId;
        void account?.pinned;
        if (!seen) { seen = true; return; }
        root?.dispatchEvent(new Event('change', { bubbles: true }));
    });

    export function selected(): { value: string; data: Record<string, string>; disabled: boolean } | null {
        const row = shown.find((r) => r.value === value);
        return row ? { value: row.value, data: { ...row.data }, disabled: row.disabled } : null;
    }
    export function setEnabled(predicate: (data: Record<string, string>) => boolean): void { allowed = predicate; }
    export function selectFirst(predicate: (row: PickerRow) => boolean): void {
        const row = shown.find((r) => !r.disabled && predicate(r));
        if (row) value = row.value;
    }
    export function accountAnswer(): AccountAnswer | null { return account; }
    export function focus(): void { root?.querySelector<HTMLElement>('[data-choice-trigger]')?.focus(); }
</script>

<div bind:this={root} class="lch-host" data-launch-choice-host>
    <LaunchChoice rows={shown} bind:value accounts={loaded ? accounts : null} followWords={appT('launch_profiles.list.follow')} {label} bind:account />
</div>

<style>
    @layer components {
        .lch-host { min-width: 0; }
    }
</style>
