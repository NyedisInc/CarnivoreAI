
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import type { CatalogContents } from './types';

    interface Props {
        itemId: string | null;
        host: Pick<CatalogHost, 'contents'>;
        t: Translate;
    }

    const { itemId, host, t }: Props = $props();

    let contents = $state<CatalogContents | null>(null);
    let busy = $state(false);
    let failure = $state<string | null>(null);

    let generation = 0;
    $effect(() => {
        void itemId;
        generation += 1;
        contents = null;
        failure = null;
        busy = false;
    });

    async function load(): Promise<void> {
        if (!itemId || !host.contents || busy) return;
        const mine = generation;
        busy = true;
        failure = null;
        try {
            const answer = await host.contents(itemId);
            if (mine === generation) contents = answer;
        } catch (error) {
            if (mine === generation) failure = error instanceof Error ? error.message : String(error ?? '');
        } finally {
            if (mine === generation) busy = false;
        }
    }
</script>

{#if host.contents && itemId}
    <section class="cbk" data-contents-block aria-label={t('skill.contents.heading')}>
        {#if !contents}
            <button type="button" class="oc-btn oc-btn--sm cbk__btn" data-contents-load disabled={busy} onclick={() => void load()}
                >{busy ? t('skill.contents.loading') : t('skill.contents.show')}</button
            >
            {#if failure}<p class="cbk__error" role="alert" data-contents-error>{t('skill.contents.failed', { reason: failure })}</p>{/if}
        {:else}
            <p class="cbk__heading">{t('skill.contents.files', { count: contents.files.length, version: contents.version })}</p>
            
            <ul class="cbk__files">
                {#each contents.files as file}
                    <li class="cbk__file" data-contents-file={file.path}>
                        <span>{file.path}</span>
                        <span class="cbk__size">{t('skill.contents.size', { count: file.size })}{file.kind === 'text' ? '' : `, ${t(`skill.contents.kind.${file.kind}`)}`}</span>
                    </li>
                {/each}
            </ul>
            <p class="cbk__heading">{t('skill.contents.body')}</p>
            <pre class="cbk__doc" data-contents-body>{contents.body}</pre>
            {#if contents.body_truncated}<p class="cbk__size">{t('skill.contents.truncated')}</p>{/if}
        {/if}
    </section>
{/if}

<style>
    .cbk {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }



    .cbk__btn {
        align-self: flex-start;
    }

    .cbk__heading {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cbk__files {
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .cbk__file {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .cbk__size {
        margin: 0;
        color: var(--oc-text-secondary);
    }

    .cbk__error {
        margin: 0;
        color: var(--oc-coral);
        font-size: 11px;
    }

    .cbk__doc {
        max-height: 260px;
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

    @media (max-width: 767px) {

        .cbk__doc {
            max-height: 40vh;
        }
    }
</style>
