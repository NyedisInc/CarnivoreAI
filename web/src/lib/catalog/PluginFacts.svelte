
<script lang="ts">
    import { KIND_KEYS } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import { mcpCommandLine } from './mcp';
    import type { PluginFacts } from './plugin-facts';
    import type { McpServer } from './types';

    interface Props {
        facts: PluginFacts;
        mcp?: readonly McpServer[];
        t: Translate;
    }

    const { facts, t, mcp = [] }: Props = $props();
</script>

<p class="parts__heading">{t(KIND_KEYS.pluginPartsHeading)}</p>

{#if facts.parts.length}
    <ul class="parts">
        {#each facts.parts as part}
            <li class="parts__item">
                {t(KIND_KEYS.pluginPartCount, {
                    label: t(part.labelKey),
                    count: part.files,
                })}
            </li>
        {/each}
    </ul>
{:else}
    <p class="parts__absent" role="status">{t(KIND_KEYS.pluginPartsAbsent)}</p>
{/if}

{#if mcp.length}
    <div class="mcp" role="note">
        <p class="mcp__heading">{t(KIND_KEYS.pluginMcpHeading)}</p>
        <p class="mcp__lead">{t(KIND_KEYS.pluginMcpLead)}</p>
        {#each mcp as server}
            <pre class="mcp__cmd">{mcpCommandLine(server)}</pre>
            {#if server.env_keys.length}
                <p class="mcp__env">{t(KIND_KEYS.pluginMcpEnv, { names: server.env_keys.join(', ') })}</p>
            {/if}
        {/each}
    </div>
{/if}

<style>
    .mcp {
        margin: 8px 0 0;
        padding: 6px 8px;
        border: 1px solid var(--oc-coral);
        border-radius: 3px;
    }

    .mcp__heading {
        margin: 0;
        color: var(--oc-coral);
        font-size: 11px;
        text-transform: lowercase;
    }

    .mcp__lead,
    .mcp__env {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .mcp__cmd {
        margin: 4px 0 0;
        padding: 4px 6px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    .parts__heading {
        margin: 6px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        text-transform: lowercase;
    }

    .parts {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 4px 0 0;
        padding: 0;
        list-style: none;
    }

    .parts__item {
        padding: 3px 6px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        color: var(--oc-text-muted);
        font-size: 11px;
    }

    .parts__absent {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }
</style>
