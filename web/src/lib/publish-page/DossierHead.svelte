
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import KindMark from '../catalog/KindMark.svelte';
    import CheckMark from './CheckMark.svelte';
    import './detail.css';
    import { clockText, dateText } from './format';
    import { changedNote, factsUnknown, kindLine, markOf, onComputerValue, selectedRecord, sentRows, threeVersions } from './item-model';
    import type { PageProps } from './props';

    const { store, t }: PageProps = $props();

    const rec = $derived(selectedRecord(store));
    const facts = $derived(store.sel ? store.facts[store.sel] : undefined);
    const rows = $derived(rec ? sentRows(store, rec) : []);
    const versions = $derived(threeVersions(rows, facts?.declared_version ?? ''));
    const line = $derived(rec ? kindLine(rec) : null);
    const note = $derived(rec ? changedNote(rec, facts, Date.now()) : null);
    const unknown = $derived(rec ? factsUnknown(store, rec) : false);
    const changedAt = $derived(facts?.changed_at ?? '');
    // could not be read
    const onComputer = $derived(onComputerValue({ folderListFailed: !!store.failure.folders, hasFolder: !!rec && rec.folder !== null, declared: versions.onComputer, none: t('publish.page.versions.none') }));
    const cells = $derived([
        { label: t('publish.page.versions.approved'), value: versions.approved, none: t('publish.page.versions.none') },
        { label: t('publish.page.versions.sent'), value: versions.sent, none: t('publish.page.versions.never') },
        { label: t('publish.page.versions.on_computer'), value: versions.onComputer, text: onComputer, none: t('publish.page.versions.none') },
    ]);
</script>

<header class="d-head" data-pp="DossierHead">
    {#if rec && line}
        <div class="d-crumb"><Button onclick={() => store.goList()}><Icon name="arrow-left" size={14} /> {t('publish.page.item.back')}</Button></div>
        <div class="d-head__row">
            <h2 class="d-name">{rec.name}</h2>
            {#if rec.harness}<span class="d-harness">{rec.harness}</span>{/if}
        </div>
        <p class="d-kind">
            <span><KindMark kind={markOf(rec)} size="md" bare {t} />{t(line.kind)}</span>
            {#if line.folder}<span>{t('publish.page.item.in_folder', { folder: t(line.folder) })}</span>{/if}
            {#if changedAt}<span>{t('publish.page.item.last_changed', { date: dateText(changedAt, t), time: clockText(changedAt, t) })}</span>{/if}
        </p>
        <dl class="d-vers">
            {#each cells as cell (cell.label)}<div><dt>{cell.label}</dt><dd data-none={cell.value && !unknown && cell.text !== '-' ? undefined : ''} class="pp-ident">{unknown ? '-' : cell.text ?? (cell.value || cell.none)}</dd></div>{/each}
        </dl>
        {#if unknown}
            <p class="d-note" data-tone="yellow" role="alert">{store.failure.facts} <Button onclick={() => void store.loadFacts(rec.location)}>{t('skill.action.retry')}</Button></p>
        {/if}
        {#if note}
            <p class="d-changed"><CheckMark result="note" shapeOnly {t} /><span>{t('publish.page.item.changed', { version: note.version, count: note.count, hours: note.hours })}</span></p>
        {/if}
    {/if}
</header>
