
<script lang="ts">
    import './detail.css';
    import { buttonAttrs } from '../base/classes';
    import { bytesText, dateText } from './format';
    import { factLines, factsUnknown, hasChecks, itemFacts, selectedRecord, sentRows } from './item-model';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import StageMark from './StageMark.svelte';
    import { stageKey, stageOf, versionStage } from './stages';

    const { store, t }: PageProps = $props();

    const FIRST_FILES = 8;

    const rec = $derived(selectedRecord(store));
    const facts = $derived(store.sel ? store.facts[store.sel] : undefined);
    const full = $derived(itemFacts(facts));
    const lines = $derived(rec ? factLines(rec, facts, t) : []);
    const rows = $derived(rec ? sentRows(store, rec) : []);
    const files = $derived(full?.files ?? []);
    const unknown = $derived(rec ? factsUnknown(store, rec) : false);
</script>

<div data-pp="ItemPanels">
    {#if rec}
        <Panel label={t('publish.page.panel.what_it_is')}>
            {#if rec.folder?.description}<p class="d-desc">{rec.folder.description}</p>{/if}
            <dl class="d-facts">
                {#each lines as line (line.label)}<div><dt>{line.label}</dt><dd>{line.value}</dd></div>{/each}
            </dl>
        </Panel>
        {#if full}
            <Panel label={t('publish.page.panel.what_is_in_it')} aux={t('publish.page.panel.files_count', { count: full.file_count })}>
                <ul class="d-files">
                    {#each files.slice(0, FIRST_FILES) as file (file.path)}<li><span class="d-files__p pp-ident">{file.path}</span><span>{bytesText(file.size, t)}</span></li>{/each}
                </ul>
                {#if files.length > FIRST_FILES}
                    <details class="d-det">
                        <summary>{t('publish.page.files.show_others', { count: files.length - FIRST_FILES })}</summary>
                        <ul class="d-files">
                            {#each files.slice(FIRST_FILES) as file (file.path)}<li><span class="d-files__p pp-ident">{file.path}</span><span>{bytesText(file.size, t)}</span></li>{/each}
                        </ul>
                    </details>
                {/if}
                {#if !full.license_file}<p class="d-note">{t('publish.page.files.no_license')}</p>{/if}
            </Panel>
        {/if}
        <Panel label={t('publish.page.panel.versions_sent')} aux={rows.length ? t('publish.page.panel.versions_count', { count: rows.length }) : ''}>
            {#if rows.length}
                <ul class="d-vl">
                    {#each rows as row (row.id)}
                        {@const stage = versionStage(row) ?? stageOf(row)}
                        <li>
                            {#snippet cells()}
                                <span class="d-vl__v pp-ident">{row.version}</span>
                                <span class="d-vl__s">{#if stage}<StageMark {stage} shapeOnly {t} />{t(stageKey(stage))}{:else if row.status === 'withdrawn'}{t('skill.publish.state.withdrawn')}{/if}</span>
                                <span class="d-vl__w">{dateText(row.created_at, t)}</span>
                                <span class="d-vl__g">{hasChecks(row) ? t('publish.page.versions.see_checks') : ''}</span>
                            {/snippet}
                            {#if hasChecks(row)}
                                <button type="button" class="d-vl__row" {...buttonAttrs('row', 'md')} onclick={() => store.openEvent(`${row.id}:gates`)}>{@render cells()}</button>
                            {:else}
                                <div class="d-vl__row">{@render cells()}</div>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {:else if !unknown}
                <p class="d-note">{t('publish.page.versions.empty')}</p>
            {/if}
        </Panel>
    {/if}
</div>
