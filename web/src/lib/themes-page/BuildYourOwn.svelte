
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { t } from '../i18n/index.svelte';

    interface Props {
        onrescan: () => void;
        onlibrary: () => void;
        onsubmit: () => void;
    }

    let { onrescan, onlibrary, onsubmit }: Props = $props();

    const example = $derived(
        JSON.stringify(
            {
                id: 'night-ops',
                name: t('themes.page.guide.example.name'),
                description: t('themes.page.guide.example.description'),
                author: 'you',
                version: '1.0.0',
                cssVars: {
                    '--color-bg': '#0a0f0c',
                    '--color-bg-page': '#060a08',
                    '--color-header-bg': '#0d1410',
                    '--color-fg': '#c8d8cc',
                    '--color-border': '#1f2e25',
                    '--color-accent': '#5fd38a',
                    '--color-success': '#5fd38a',
                    '--color-warning': '#e8c06a',
                    '--color-danger': '#e5655a',
                },
                xterm: {
                    background: '#060a08',
                    foreground: '#c8d8cc',
                    cursor: '#5fd38a',
                    green: '#5fd38a',
                    red: '#e5655a',
                },
                background: { image: 'background.webp', dim: 0.85 },
            },
            null,
            2,
        ),
    );

    const STEPS = ['folder', 'manifest', 'art', 'effects', 'load'] as const;
</script>

<section class="tbyo" aria-labelledby="tbyo-title">
    <h2 class="tbyo-title" id="tbyo-title">{t('themes.page.guide.title')}</h2>
    <p class="tbyo-lead">{t('themes.page.guide.lead')}</p>

    <ol class="tbyo-steps">
        {#each STEPS as step, index (step)}
            <li class="tbyo-step">
                <span class="tbyo-num" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                <div class="tbyo-copy">
                    <h3>{t(`themes.page.guide.${step}.title`)}</h3>
                    <p>{t(`themes.page.guide.${step}.body`)}</p>
                    {#if step === 'folder'}
                        <code class="tbyo-path">{t('themes.page.guide.path')}</code>
                        <p class="tbyo-fine">{t('themes.page.guide.override')}</p>
                    {:else if step === 'manifest'}
                        <pre class="tbyo-code"><code>{example}</code></pre>
                    {:else if step === 'load'}
                        <Button onclick={onrescan}>{t('themes.page.rescan')}</Button>
                    {/if}
                </div>
            </li>
        {/each}
    </ol>

    <div class="tbyo-share">
        <h3>{t('themes.page.guide.share.title')}</h3>
        <p>{t('themes.page.guide.share.body')}</p>
        <div class="tbyo-row">
            <Button aria-describedby="tbyo-soon" onclick={onsubmit}>{t('themes.page.submit.action')}</Button>
            <Button onclick={onlibrary}>{t('themes.page.library')}</Button>
        </div>
        <p class="tbyo-fine" id="tbyo-soon">{t('themes.page.submit.hint')}</p>
    </div>
</section>

<style>
    .tbyo {
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-width: 0;
    }

    .tbyo-title {
        margin: 0;
        font-size: var(--oc-fs-label, 12px);
        font-weight: 700;
        letter-spacing: var(--oc-tracking-title, 0.12em);
        text-transform: uppercase;
        color: var(--oc-orange);
    }

    .tbyo-lead,
    .tbyo-copy p,
    .tbyo-share p {
        margin: 0;
        font-size: var(--oc-fs-body, 13px);
        line-height: 1.55;
        color: var(--oc-text-secondary);
    }

    .tbyo-steps {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin: 0;
        padding: 0;
        list-style: none;
        border-top: 1px solid var(--oc-line-faint);
    }

    .tbyo-step {
        display: grid;
        grid-template-columns: 28px 1fr;
        gap: 10px;
        padding: 12px 0;
        border-bottom: 1px solid var(--oc-line-faint);
    }

    .tbyo-num {
        font-size: var(--oc-fs-label, 12px);
        font-weight: 700;
        color: var(--oc-orange);
    }

    .tbyo-copy {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
    }

    .tbyo-copy h3,
    .tbyo-share h3 {
        margin: 0;
        font-size: var(--oc-fs-label, 12px);
        font-weight: 600;
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-bright);
    }

    .tbyo-path,
    .tbyo-code {
        display: block;
        margin: 0;
        padding: 8px 10px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
        background: var(--oc-ground-field, var(--oc-ground-page));
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        line-height: 1.5;
        color: var(--oc-green);
        overflow-x: auto;
        overflow-wrap: anywhere;
    }

    .tbyo-code {
        max-height: 260px;
        overflow: auto;
        white-space: pre;
        overflow-wrap: normal;
    }

    .tbyo-fine {
        font-size: var(--oc-fs-label, 12px) !important;
        color: var(--oc-text-dim) !important;
    }

    .tbyo-share {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 12px;
        border: 1px dashed var(--oc-line-rule);
        border-radius: 2px;
    }

    .tbyo-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    @media (max-width: 1023px) {
        .tbyo-copy :global([data-btn]),
        .tbyo-row :global([data-btn]) {
            min-height: var(--oc-tap);
        }
    }

    .tbyo-copy :global([data-btn]) {
        align-self: flex-start;
    }
</style>
