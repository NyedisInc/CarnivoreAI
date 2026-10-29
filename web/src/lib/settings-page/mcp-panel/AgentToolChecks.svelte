<!-- app settings tools running sessions -->
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Checkbox from '../../base/Checkbox.svelte';
    import State from '../../base/State.svelte';
    import { errorText } from '../panel-kit/error-text';
    import { fetchAgentTools, setAgentTools, type AgentTools, type Fetcher } from './api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let held = $state<AgentTools | null>(null);
    let busy = $state(false);
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            held = await fetchAgentTools(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function flip(change: Partial<AgentTools>): Promise<void> {
        busy = true;
        problem = '';
        try {
            held = await setAgentTools(change, fetcher);
        } catch (error) {
            problem = errorText(error);
            await load();
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm__field" data-mcp="agent-tools">
    {#if held}
        <Checkbox label={t('settings.mcp.agent_task_manager')} hint={t('settings.mcp.agent_task_manager_hint')}
            bind:checked={() => held?.huddle ?? false, (next) => void flip({ huddle: next })} disabled={busy} data-mcp="agent-task-manager" />
        <Checkbox label={t('settings.mcp.agent_swarm')} hint={t('settings.mcp.agent_swarm_hint')}
            bind:checked={() => held?.swarm ?? false, (next) => void flip({ swarm: next })} disabled={busy} data-mcp="agent-swarm" />
        <Checkbox label={t('settings.mcp.agent_app_settings')} hint={t('settings.mcp.agent_app_settings_hint')}
            bind:checked={() => held?.app_settings ?? false, (next) => void flip({ app_settings: next })} disabled={busy} data-mcp="agent-app-settings" />
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-mcp="agent-tools-problem" />{/if}
</div>
