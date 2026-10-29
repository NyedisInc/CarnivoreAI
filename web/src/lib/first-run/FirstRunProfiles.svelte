
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { Button } from '../base';
    import LaunchProfileExamples from '../launch-profiles-page/LaunchProfileExamples.svelte';
    import { createLaunchProfilesApi, errorText, type Harness, type ProfileRow } from '../launch-profiles-page/api';
    import { EXAMPLES, exampleForm, offeredExamples, type Example } from '../launch-profiles-page/examples';
    import { formToProfile, uniqueId } from '../launch-profiles-page/form-model';

    let { onContinue }: { onContinue: () => void } = $props();

    const api = createLaunchProfilesApi();
    let loading = $state(true);
    let rows = $state<ProfileRow[]>([]);
    let revision = $state(0);
    let used = $state<ReadonlySet<string>>(new Set());
    let busy = $state(false);
    let problem = $state<string | null>(null);

    const offered = $derived<Example[]>(offeredExamples(rows));
    const found = $derived(Array.from(new Set<Harness>(rows.filter((r) => r.installed !== false && (r.harness === 'claude' || r.harness === 'codex')).map((r) => r.harness))));
    const taken = $derived(new Set(rows.map((r) => r.id)));

    onMount(() => void load());

    async function load(): Promise<void> {
        try {
            const out = await api.list();
            rows = out.profiles;
            revision = out.revision;
        } catch (err) {
            console.warn('FirstRunProfiles: launch profiles unreadable, skipping the step', errorText(err));
            onContinue();
            return;
        }
        loading = false;
        if (offered.length === 0) onContinue();
    }

    async function add(id: string): Promise<void> {
        const ex = EXAMPLES.find((e) => e.id === id);
        if (!ex || busy) return;
        busy = true; problem = null;
        const form = exampleForm(ex, t(`launch_profiles.template.${ex.id}`), []);
        const profile = formToProfile({ ...form, id: uniqueId(form.id, taken) });
        try {
            const out = await api.create(profile, revision);
            revision = out.revision;
            rows = [...rows, { ...profile, installed: true } as ProfileRow];
            used = new Set([...used, id]);
        } catch (err) {
            problem = errorText(err);
        }
        busy = false;
    }
</script>

{#if loading}
    <p class="first-run__text" role="status">{t('first_run.profiles.checking')}</p>
{:else}
    <h1 class="first-run__head">{t('first_run.profiles.title')}</h1>
    <p class="first-run__tag">{t('first_run.profiles.label')}</p>
    <p class="first-run__text" data-first-run="profiles-found">
        {found.length > 0 ? t('first_run.profiles.found', { agents: found.join(', ') }) : t('first_run.profiles.none_found')}
    </p>
    <p class="first-run__text">{t('first_run.profiles.body')}</p>
    <LaunchProfileExamples examples={offered} {used} open t={t} actionKey="first_run.profiles.add" doneKey="first_run.profiles.added" disabled={busy} onUse={(id) => void add(id)} />
    {#if problem}<p class="first-run__problem" role="alert" data-first-run="profiles-error">{problem}</p>{/if}
    <div class="first-run__actions">
        <Button variant="confirm" data-go data-first-run="profiles-continue" onclick={onContinue}>{t('first_run.profiles.continue')}</Button>
    </div>
{/if}
