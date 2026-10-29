<!-- could not -->
<script lang="ts">
    import { mcpCommandLine } from '../catalog/mcp';
    import type { Translate } from '../sessions/types';
    import type { CommandFacts } from './catalog-plugins.svelte';
    import './catalog-plugins.css';

    interface Props {
        facts: CommandFacts;
        t: Translate;
    }

    const { facts, t }: Props = $props();
</script>

{#if facts.kind === 'loading'}
    <p class="cpf__note" role="status">{t('plugins.page.catalog.checking')}</p>
{:else if facts.kind === 'failed'}
    <p class="cpf__note cpf__note--warn" role="status">{t('plugins.page.catalog.preview_failed')}</p>
{:else if facts.kind === 'ready' && (facts.servers.length > 0 || facts.scripts.length > 0)}
    <div class="cpf" data-catalog-command>
        {#if facts.servers.length > 0}
            <p class="cpf__lead">{t('plugins.page.catalog.runs')}</p>
            {#each facts.servers as server (server.name)}
                <pre class="cpf__cmd">{mcpCommandLine(server)}</pre>
                {#if server.env_keys.length > 0}
                    <p class="cpf__note">{t('plugins.page.catalog.env', { names: server.env_keys.join(', ') })}</p>
                {/if}
            {/each}
        {/if}
        {#if facts.scripts.length > 0}
            <p class="cpf__lead">{t('plugins.page.catalog.scripts')}</p>
            <pre class="cpf__cmd">{facts.scripts.join('\n')}</pre>
        {/if}
    </div>
{/if}
