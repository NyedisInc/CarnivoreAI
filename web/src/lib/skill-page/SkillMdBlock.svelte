
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { refusalOf, type Fetcher, type SkillsContext } from '../skills-page/skills-api';
    import type { SkillLocationRow } from '../skills-page/skills-types';
    import type { Translate } from '../sessions/types';
    import MdFormatted from './MdFormatted.svelte';
    import { agoWords, linesOf } from './model';
    import {
        listSkillMdVersions,
        readSkillMd,
        restoreSkillMdVersion,
        saveSkillMd,
        StaleBaseError,
        type SkillMdRead,
        type SkillMdVersion,
        type SkillMdVersionList,
    } from './skill-md-api';

    interface Props {
        location: SkillLocationRow;
        context: SkillsContext;
        fetcher: Fetcher;
        t: Translate;
        onLoaded?: (read: SkillMdRead) => void;
    }

    const { location, context, fetcher, t, onLoaded }: Props = $props();

    let md = $state<SkillMdRead | null>(null);
    let loadError = $state<string | null>(null);
    let versions = $state<SkillMdVersion[] | null>(null);
    let newest = $state<SkillMdVersion | null>(null);
    let versionsError = $state<string | null>(null);
    let mode = $state<'fmt' | 'raw' | 'edit'>('fmt');
    let back: 'fmt' | 'raw' = 'fmt';
    let draft = $state('');
    let note = $state('');
    let busy = $state(false);
    let conflict = $state(false);
    let message = $state('');
    let failure = $state<string | null>(null);
    let versionsOpen = $state(false);
    let editor = $state<HTMLTextAreaElement | null>(null);

    const text = $derived(md?.body ?? '');
    const lines = $derived(linesOf(text));
    const current = $derived((versions?.length ?? 0) + 1);
    const readOnly = $derived(location.read_only);
    const tooLarge = $derived(md?.body_truncated === true);
    const changed = $derived(md !== null && draft !== md.body);

    async function load(): Promise<void> {
        try {
            md = await readSkillMd(location.location_id, context, fetcher);
            loadError = null;
            onLoaded?.(md);
        } catch (error) {
            md = null;
            loadError = refusalOf(error, t('skp.md.error'));
        }
        await loadVersions();
    }

    async function loadVersions(): Promise<void> {
        try {
            const list: SkillMdVersionList = await listSkillMdVersions(location.location_id, context, fetcher);
            versions = list.versions;
            newest = list.current;
            versionsError = null;
        } catch (error) {
            versions = null;
            newest = null;
            versionsError = refusalOf(error, t('skp.md.versions_error'));
        }
    }

    onMount(() => void load());

    async function startEdit(): Promise<void> {
        if (!md) return;
        back = mode === 'raw' ? 'raw' : 'fmt';
        mode = 'edit';
        draft = md.body;
        note = '';
        message = '';
        failure = null;
        conflict = false;
        versionsOpen = false;
        await tick();
        editor?.focus();
    }

    function cancelEdit(): void {
        mode = back;
        conflict = false;
        failure = null;
    }

    async function save(): Promise<void> {
        if (!md || busy || !changed) return;
        busy = true;
        failure = null;
        try {
            await saveSkillMd(location.location_id, draft, md.sha256, note.trim() || null, context, fetcher);
            mode = back;
            conflict = false;
            message = t('skp.md.saved', { version: current + 1 });
            await load();
        } catch (error) {
            if (error instanceof StaleBaseError) conflict = true;
            else failure = refusalOf(error, t('skp.md.save_error'));
        } finally {
            busy = false;
        }
    }

    async function reloadFromDisk(): Promise<void> {
        conflict = false;
        mode = back;
        message = '';
        await load();
    }

    async function rollBack(version: SkillMdVersion, number: number): Promise<void> {
        if (!md || busy) return;
        busy = true;
        failure = null;
        try {
            await restoreSkillMdVersion(location.location_id, version.id, md.sha256, context, fetcher);
            message = t('skp.md.rolled_back', { from: number, to: current + 1 });
            await load();
        } catch (error) {
            if (error instanceof StaleBaseError) {
                conflict = true;
                failure = null;
            } else failure = refusalOf(error, t('skp.md.save_error'));
        } finally {
            busy = false;
        }
    }

    function when(epochSeconds: number): string {
        const d = new Date(epochSeconds * 1000);
        if (Number.isNaN(d.getTime())) return '';
        const ago = agoWords(Date.now() / 1000 - epochSeconds, t);
        if (ago) return ago;
        const p = (n: number): string => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    function noteOf(version: SkillMdVersion): string {
        if (version.note) return version.note;
        return t(version.action === 'restore' ? 'skp.md.action_restore' : version.action === 'baseline' ? 'skp.md.action_baseline' : 'skp.md.action_edit');
    }
</script>

<div class="skp-md" data-skill-md-block data-mode={mode}>
    <div class="skp-md__bar">
        <span class="skp-label">{t('skp.md.label')}</span>
        {#if md}
            <span class="skp-note">
                {mode === 'edit' ? t('skp.md.editing', { version: current + 1 }) : t('skp.md.showing', { version: current, count: lines.length })}
            </span>
        {/if}
        <div class="skp-md__tools">
            {#if mode === 'edit'}
                <input type="text" class="skp-input skp-vnote" aria-label={t('skp.md.note_label')} placeholder={t('skp.md.note')} maxlength="80" bind:value={note} />
                <button type="button" class="skp-tool skp-tool--primary" data-act="save-version" disabled={!changed || busy} onclick={() => void save()}>{t('skp.md.save')}</button>
                <button type="button" class="skp-tool" data-act="cancel-edit" onclick={cancelEdit}>{t('skp.md.cancel')}</button>
            {:else}
                <button type="button" class="skp-tool" data-act="view-md" aria-pressed={mode === 'raw'} disabled={!md} onclick={() => { mode = mode === 'raw' ? 'fmt' : 'raw'; message = ''; }}>{t('skp.md.view_md')}</button>
                <button type="button" class="skp-tool" data-act="edit" disabled={!md || readOnly || tooLarge} aria-describedby={readOnly || tooLarge ? 'skp-md-why' : undefined} onclick={() => void startEdit()}>{t('skp.md.edit')}</button>
                {#if !readOnly}
                    <button type="button" class="skp-tool" data-act="versions" aria-expanded={versionsOpen} onclick={() => { versionsOpen = !versionsOpen; message = ''; }}>{versions ? t('skp.md.versions_n', { count: current }) : t('skp.md.versions')}</button>
                {/if}
            {/if}
        </div>
    </div>
    {#if readOnly && mode !== 'edit'}<p class="skp-md__msg" id="skp-md-why">{t('skp.md.read_only')}</p>{/if}
    {#if tooLarge && mode !== 'edit'}<p class="skp-md__msg" id="skp-md-why">{t('skp.md.too_large', { size: md?.size ?? 0 })}</p>{/if}
    {#if message && mode !== 'edit'}<p class="skp-md__msg" role="status" data-msg>{message}</p>{/if}
    {#if conflict}
        <div class="skp-md__msg skp-md__msg--bad" role="alert" data-skill-md-conflict>
            <span>{t('skp.md.conflict')}</span>
            <button type="button" class="skp-tool" data-act="reload-disk" onclick={() => void reloadFromDisk()}>{t('skp.md.reload')}</button>
        </div>
    {/if}
    {#if failure}<p class="skp-md__msg skp-md__msg--bad" role="alert">{failure}</p>{/if}
    {#if versionsOpen && mode !== 'edit' && !readOnly}
        <ul class="skp-vers" aria-label={t('skp.md.versions_label')} data-skill-md-versions>
            {#if versionsError}
                <li class="skp-ver"><span class="skp-ver__n">{versionsError}</span></li>
            {:else if versions}
                <li class="skp-ver" data-current>
                    <b>v{current}</b>
                    {#if newest}<span class="skp-ver__t">{when(newest.created_at)}</span>{/if}
                    <span class="skp-ver__n">{newest ? noteOf(newest) : t('skp.md.current_file')}</span>
                    <span class="skp-note">{t('skp.md.lines', { count: newest?.lines ?? lines.length })}</span>
                    <span class="skp-ver__cur">{t('skp.md.current')}</span>
                </li>
                {#each versions as version, i (version.id)}
                    {@const number = versions.length - i}
                    <li class="skp-ver" data-v={number}>
                        <b>v{number}</b>
                        <span class="skp-ver__t">{when(version.created_at)}</span>
                        <span class="skp-ver__n">{noteOf(version)}</span>
                        <span class="skp-note">{t('skp.md.lines', { count: version.lines ?? 0 })}</span>
                        <button type="button" class="skp-tool" data-act="rollback" disabled={busy || version.redacted === true} onclick={() => void rollBack(version, number)}>{t('skp.md.roll_back')}</button>
                    </li>
                {/each}
            {/if}
        </ul>
    {/if}
    {#if mode === 'edit'}
        <div class="skp-md__body skp-md__body--edit">
            <textarea class="skp-edit" aria-label={t('skp.md.edit_label', { name: location.name })} spellcheck="false" wrap="off" bind:this={editor} bind:value={draft}></textarea>
        </div>
    {:else if md}
        <div class="skp-md__body" role="region" aria-label={t('skp.md.region', { name: location.name })}>
            {#if mode === 'raw'}
                {#each lines as line, i (i)}
                    <div class="skp-md__l" data-h={/^#/.test(line) ? '' : null}><span>{i + 1}</span><span>{line || ' '}</span></div>
                {/each}
            {:else}
                <MdFormatted text={md.body} />
            {/if}
        </div>
    {:else if loadError}
        <p class="skp-md__msg skp-md__msg--bad" role="alert" data-skill-md-error>{loadError}</p>
    {:else}
        <p class="skp-md__msg" role="status">{t('skp.md.loading')}</p>
    {/if}
</div>
