
<script lang="ts">
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { fetchStatus, type Fetcher, type McpTool } from '../settings-page/mcp-panel/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = appT, fetcher }: Props = $props();

    let tools = $state<readonly McpTool[] | null>(null);
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            tools = (await fetchStatus(fetcher)).tools;
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();
</script>

<div class="mcp-tools" data-docs-mcp-tools>
    {#if tools}
        {#each tools as tool (tool.name)}
            <p class="mcp-tools__row" data-docs-mcp-tool={tool.name}>
                <code class="mcp-tools__name">{tool.name}</code>
                {#if tool.write}<span class="mcp-tools__tag">{t('docs.mcp.write_tool')}</span>{/if}
                {tool.description}
            </p>
        {/each}
    {:else if problem}
        <p class="mcp-tools__note" role="alert">{t('docs.mcp.failed', { reason: problem })}</p>
    {:else}
        <p class="mcp-tools__note">{t('docs.mcp.loading')}</p>
    {/if}
</div>

<style>
  @layer components {
    .mcp-tools {
        max-width: 78ch;
        margin-top: var(--oc-space-2);
        border-top: var(--oc-border, 1px) solid var(--oc-line-rule);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.5;
    }

    .mcp-tools__row,
    .mcp-tools__note {
        margin: 0;
        padding: var(--oc-space-1-5) 0;
        border-bottom: var(--oc-border, 1px) solid var(--oc-line-rule);
        color: var(--oc-text-secondary);
    }

    .mcp-tools__name {
        font-family: var(--font-mono);
        color: var(--oc-text-primary);
    }

    .mcp-tools__tag {
        padding: 0 var(--oc-space-1);
        border: var(--oc-border, 1px) solid var(--oc-coral);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--oc-coral);
    }
  }
</style>
