
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { Button } from '../base';
    import CopyField from '../settings-page/CopyField.svelte';
    import { fetchAgentCheck, type AgentCheck } from './agent-check-api';

    let { onContinue }: { onContinue: () => void } = $props();

    let result = $state<AgentCheck | null>(null);
    let checking = $state(true);

    async function check(): Promise<void> {
        checking = true;
        result = await fetchAgentCheck();
        checking = false;
    }

    onMount(() => void check());

    const claudeKey = $derived(checking ? 'first_run.agent.checking' : result === null ? 'first_run.agent.unknown' : result.claude ? 'first_run.agent.claude_found' : 'first_run.agent.claude_missing');
    const missing = $derived(!checking && result !== null && !result.claude);
</script>

<h1 class="first-run__head">{t('first_run.agent.title')}</h1>
<p class="first-run__tag">{t('first_run.agent.label')}</p>
<p class="first-run__text" role="status" data-first-run="claude" data-first-run-agent={checking ? 'checking' : result === null ? 'unknown' : result.claude ? 'found' : 'missing'}>{t(claudeKey)}</p>
{#if missing}
    <p class="first-run__text" data-first-run="agent-install">{t('first_run.agent.install')}</p>
    <CopyField value={t('first_run.agent.install_cmd')} {t} label={t('first_run.agent.install')} valueAttrs={{ 'data-first-run': 'install-cmd' }} />
    <p class="first-run__text" data-first-run="agent-signin">{t('first_run.agent.signin')}</p>
{/if}
{#if !checking && result?.codex}
    <p class="first-run__text" data-first-run="codex">{t('first_run.agent.codex_found')}</p>
{/if}
<div class="first-run__actions">
    {#if !checking && !(result?.claude)}
        <Button data-first-run="recheck" onclick={() => void check()}>{t('first_run.agent.recheck')}</Button>
    {/if}
    <Button variant="confirm" data-go data-first-run="agent-continue" onclick={onContinue}>{t('first_run.done.continue')}</Button>
</div>
