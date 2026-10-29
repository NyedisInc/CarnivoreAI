
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { bodyHeadingKey } from '../../../../client/js/labels/catalog-kind.js';
    import ReviewBlock from './ReviewBlock.svelte';
    import type { Translate } from '../sessions/types';
    import { MAX_NAME_CHARS, MAX_PUBLISHER_CHARS, MAX_VERSION_CHARS } from './card';
    import {
        MAX_DIGEST_CHARS,
        MAX_PREVIEW_FILES,
        boundedList,
        boundedPath,
        clipChars,
    } from './bounds';
    import { isScriptFile } from './scripts';
    import type { InstallPreview } from './types';

    interface Props {
        preview: InstallPreview;
        kind?: string | null;
        t: Translate;
        part?: 'all' | 'facts' | 'advanced';
    }

    const { preview, kind = null, t, part = 'all' }: Props = $props();
    const showFacts = $derived(part !== 'advanced');
    const showDetail = $derived(part !== 'facts');
    const fullFacts = $derived(part === 'all');

    const publisher = $derived(clipChars(preview.publisher, MAX_PUBLISHER_CHARS));
    const version = $derived(clipChars(preview.version, MAX_VERSION_CHARS));
    const keyId = $derived(clipChars(preview.key_id, MAX_NAME_CHARS));
    const indexHost = $derived(clipChars(preview.index_host, MAX_NAME_CHARS));

    const listed = $derived(boundedList(preview.files, MAX_PREVIEW_FILES));

    const digest = $derived(
        clipChars(preview.digest, MAX_DIGEST_CHARS)
            ?? clipChars(preview.digest_prefix, MAX_DIGEST_CHARS),
    );
</script>

{#if showFacts}
<dl class="sheet__facts">
    {#if publisher}
        <dt>{t(SKILL_KEYS.sheetPublisher)}</dt>
        <dd>{publisher}</dd>
    {/if}
    {#if version}
        <dt>{t(SKILL_KEYS.sheetVersion)}</dt>
        <dd>{version}</dd>
    {/if}
    {#if fullFacts && keyId}
        <dt>{t(SKILL_KEYS.sheetKeyId)}</dt>
        <dd>
            {keyId}
            
            {#if preview.pinned === true}
                <span class="sheet__pin">{t(SKILL_KEYS.sheetPinned)}</span>
            {/if}
        </dd>
    {/if}
    {#if fullFacts && indexHost}
        <dt>{t(SKILL_KEYS.sheetIndexHost)}</dt>
        <dd>{indexHost}</dd>
    {/if}
    {#if fullFacts && digest}
        <dt>{t(SKILL_KEYS.sheetDigest)}</dt>
        
        <dd>{digest}</dd>
    {/if}
    {#if fullFacts && preview.total_bytes !== null && preview.total_bytes !== undefined}
        <dt>{t(SKILL_KEYS.sheetTotal)}</dt>
        <dd>{t(SKILL_KEYS.sheetBytes, { count: preview.total_bytes })}</dd>
    {/if}
</dl>
{/if}

{#if showDetail}


<div class="sheet__review"><ReviewBlock review={preview.review ?? null} {t} /></div>

{#if part === 'all' && preview.body}
    <p class="sheet__heading">{t(bodyHeadingKey(kind))}</p>
    <p class="sheet__body-size">{t(SKILL_KEYS.sheetBodySize, { count: preview.body.length })}</p>
    <pre class="sheet__body">{preview.body}</pre>
{/if}

{#if listed.shown.length}
    <p class="sheet__heading">{t(SKILL_KEYS.sheetFilesHeading)}</p>
    <ul class="sheet__files">
        {#each listed.shown as file}
            <li class="sheet__file" class:sheet__file--exec={isScriptFile(file)}>
                <span class="sheet__file-path">{boundedPath(file)}</span>
                <!-- nothing at all -->
                {#if isScriptFile(file)}
                    <span class="sheet__file-exec">{t(SKILL_KEYS.consentMarked)}</span>
                {/if}
                {#if file.size !== null && file.size !== undefined}
                    <span class="sheet__file-size">{t(SKILL_KEYS.sheetBytes, { count: file.size })}</span>
                {/if}
            </li>
        {/each}
    </ul>
    {#if listed.hidden > 0}
        
        <p class="sheet__more" role="status">
            {t(SKILL_KEYS.filesMore, { count: listed.hidden })}
        </p>
    {/if}
{/if}
{/if}

<style>
    .sheet__heading {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .sheet__facts {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 2px 10px;
        margin: 0;
        font-family: var(--font-mono);
        font-size: 11px;
    }

    .sheet__facts dt {
        color: var(--oc-text-secondary);
    }

    .sheet__facts dd {
        margin: 0;
        color: var(--oc-text-primary);
        overflow-wrap: anywhere;
    }

    .sheet__pin {
        margin-left: 6px;
        padding: 0 4px;
        border: 1px solid var(--oc-green);
        border-radius: 3px;
        color: var(--oc-green);
        font-size: 10px;
        text-transform: uppercase;
    }

    .sheet__body-size {
        margin: -6px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .sheet__body {
        max-height: 220px;
        overflow: auto;
        margin: 0;
        padding: 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    .sheet__files {
        max-height: 160px;
        overflow: auto;
        margin: 0;
        padding: 0;
        list-style: none;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
    }

    .sheet__file {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 2px 8px;
        border-bottom: 1px solid var(--oc-line-faint);
        font-family: var(--font-mono);
        font-size: 11px;
    }

    .sheet__file:last-child {
        border-bottom: none;
    }

    .sheet__file-path {
        color: var(--oc-text-primary);
        overflow-wrap: anywhere;
    }

    .sheet__file-size {
        color: var(--oc-text-secondary);
        flex-shrink: 0;
    }

    .sheet__more {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.4;
    }

    .sheet__review {
        margin: 0 0 4px;
    }

    .sheet__file--exec .sheet__file-path {
        color: var(--oc-yellow);
    }

    .sheet__file-exec {
        flex-shrink: 0;
        margin-left: auto;
        padding: 0 5px;
        border: 1px solid var(--oc-yellow);
        border-radius: 3px;
        color: var(--oc-yellow);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    @media (max-width: 767px) {
        .sheet__body {
            max-height: 40vh;
        }
    }
</style>
