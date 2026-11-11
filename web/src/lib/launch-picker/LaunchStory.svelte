
<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { Button, Field, Select, type SelectChoice } from '../base';
    import { resourcePush } from '../resource-push/boot';
    import { failureReason } from '../errors/failure-reason';
    import type { Translate } from '../sessions/types';
    import { PARENT_KIND, candidatesOf, createStoryApi, groupItems, hasChoices, rowVisible, storyAnswer, type Candidate, type ItemKind, type StoryApi, type WorkItem, type WorkItemList } from './story-model';

    interface Props {
        t: Translate;
        answer: string | null;
        api?: StoryApi;
        pollMs?: number;
    }
    let { t, answer = $bindable(), api: injected, pollMs = 60000 }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: StoryApi = injected ?? createStoryApi();

    let list = $state<WorkItemList | null>(null);
    let extra = $state<WorkItem[]>([]);
    let query = $state('');
    let picked = $state('');
    let adding = $state(false);
    let kind = $state<ItemKind>('story');
    let parent = $state('');
    let title = $state('');
    let busy = $state(false);
    let failure = $state('');
    let candidates = $state<Candidate[]>([]);

    const items = $derived([...(list?.items ?? []), ...extra.filter((e) => !(list?.items ?? []).some((i) => i.id === e.id))]);
    const pickedItem = $derived(items.find((i) => i.id === picked));
    const groups = $derived(groupItems(items, query));
    const parentKind = $derived(PARENT_KIND[kind]);
    const parents = $derived(parentKind ? items.filter((i) => i.kind === parentKind) : []);

    const options = $derived.by((): SelectChoice[] => {
        const label = (i: WorkItem): string => `${i.kind}: ${i.title}`;
        const out: SelectChoice[] = [{ value: '', label: t('argent.picker.skip') }];
        if (pickedItem && !groups.some((g) => g.items.some((i) => i.id === pickedItem.id))) out.push({ value: pickedItem.id, label: label(pickedItem) });
        for (const g of groups) out.push({ group: t(`argent.picker.group.${g.key}`), options: g.items.map((i) => ({ value: i.id, label: label(i) })) });
        return out;
    });
    const kindOptions = $derived((['project', 'feature', 'story'] as const).map((k) => ({ value: k, label: k })));
    const parentOptions = $derived([{ value: '', label: '-' }, ...parents.map((p) => ({ value: p.id, label: p.title }))]);
    const canCreate = $derived(!busy && title.trim().length > 0 && (parentKind === null || parent !== ''));

    $effect(() => { answer = storyAnswer(picked, items); });

    async function load(): Promise<void> {
        try { list = await api.list(); } catch {  }
    }
    onMount(() => { void load(); });
    const stop = resourcePush().pushOrPoll(() => void load(), pollMs, ['argent_work_items']);
    onDestroy(stop);

    async function create(): Promise<void> {
        busy = true; failure = ''; candidates = [];
        try {
            const row = await api.create(kind, parentKind ? parent : null, title.trim());
            extra = [...extra, row];
            picked = row.id; title = ''; adding = false;
            void load();
        } catch (err) {
            candidates = candidatesOf(err);
            if (!candidates.length) failure = failureReason(err);
        }
        busy = false;
    }

    function join(c: Candidate): void {
        extra = [...extra, { id: c.id, kind: c.kind, parent_id: null, title: c.title }];
        picked = c.id; candidates = []; title = ''; adding = false;
    }
</script>

{#if rowVisible(list)}
    <div class="lst" data-launch-story>
        <label class="lst-label" for="lst-pick">{t('argent.picker.label')}</label>
        {#if hasChoices(list) || extra.length}
            <Field id="lst-search" block type="search" spellcheck="false" autocomplete="off" aria-label={t('argent.picker.search')} placeholder={t('argent.picker.search')} bind:value={query} data-lst-search />
            <Select id="lst-pick" bind:value={picked} {options} aria-label={t('argent.picker.label')} data-lst-pick />
        {:else}
            <p class="lst-note" data-lst-unavailable>{t('argent.picker.unavailable')}</p>
            <Select id="lst-pick" bind:value={picked} {options} aria-label={t('argent.picker.label')} data-lst-pick />
        {/if}
        {#if adding}
            <Select id="lst-kind" bind:value={kind} options={kindOptions} aria-label={t('argent.picker.new.kind')} data-lst-kind onchange={() => (parent = '')} />
            {#if parentKind}<Select id="lst-parent" bind:value={parent} options={parentOptions} aria-label={t('argent.picker.new.parent', { kind: parentKind })} data-lst-parent />{/if}
            <Field id="lst-title" block type="text" spellcheck="false" autocomplete="off" maxlength={200} placeholder={t('argent.picker.new.title')} aria-label={t('argent.picker.new.title')} bind:value={title} data-lst-title />
            {#if candidates.length}
                <p class="lst-note" data-lst-conflict>{t('argent.picker.new.similar')}</p>
                {#each candidates as c (c.id)}
                    <div><Button data-lst-join={c.id} onclick={() => join(c)}>{t('argent.picker.new.join', { title: c.title })}</Button></div>
                {/each}
            {/if}
            {#if failure}<p class="lst-error" role="alert">{t('argent.picker.new.failed', { reason: failure })}</p>{/if}
            <div class="lst-actions">
                <Button disabled={!canCreate} data-lst-create onclick={create}>{t('argent.picker.new.create')}</Button>
                <Button data-lst-cancel onclick={() => { adding = false; candidates = []; failure = ''; }}>{t('argent.picker.new.cancel')}</Button>
            </div>
        {:else}
            <div><Button data-lst-new onclick={() => (adding = true)}>{t('argent.picker.new')}</Button></div>
        {/if}
    </div>
{/if}

<style>
  @layer components {
    .lst { display: flex; flex-direction: column; gap: var(--oc-space-1); min-width: 0; font-family: var(--font-mono); }
    .lst-label { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    .lst-note { margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }
    .lst-error { margin: 0; padding: var(--oc-space-1); border-left: 2px solid var(--oc-coral); background: var(--oc-ground-field); color: var(--oc-text-primary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }
    .lst-actions { display: flex; gap: var(--oc-space-1); flex-wrap: wrap; }
    @media (max-width: 700px) {
      .lst :global([data-field]) { width: 100%; min-height: 44px; }
    }
  }
</style>
