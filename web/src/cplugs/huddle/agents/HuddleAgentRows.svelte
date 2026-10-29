<script lang="ts">
  import { t } from '../../sdk';
  import { TaskMark } from '../../sdk/ui';
  import { swarmRoster, startSwarmRoster } from './agent-roster.svelte';
  import { openAgentPage } from './agent-page.svelte';

  $effect(() => startSwarmRoster());
</script>

{#if swarmRoster.agents.length > 0}
  <section class="hdr-agents" data-huddle-agents>
    <h2 class="hdr-agents-label">{t('cplug.huddle.agents.label')}</h2>
    <ul class="hdr-agents-list">
      {#each swarmRoster.agents as agent (agent.id)}
        <li>
          <button type="button" class="hdr-agent" data-huddle-agent={agent.id} data-agent-drawer-opener data-agent-state={agent.state}
                  onclick={() => openAgentPage(agent.id)}>
            <span class="hdr-agent-name"><TaskMark rank={agent.rank} />{agent.display_name}</span>
            <span class="hdr-agent-state">{t(`cplug.huddle.chat.state.${agent.state}`)}</span>
          </button>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  @layer components {
    .hdr-agents {
      flex: none;
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hdr-agents-label {
      margin: 0;
      padding: 6px var(--oc-space-2) 4px;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      font-weight: 400;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdr-agents-list {
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .hdr-agent {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      min-width: 0;
      padding: 4px var(--oc-space-2);
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }

    .hdr-agent:hover {
      background: var(--oc-ground-hover);
      color: var(--oc-text-bright);
    }

    .hdr-agent-name {
      min-width: 0;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdr-agent-state {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .hdr-agent[data-agent-state='awake'] .hdr-agent-state {
      color: var(--oc-green);
    }
  }
</style>
