<script lang="ts">
  /* pop-out window */
  import { onMount } from 'svelte';
  import { auth, initAuth, startEvents } from '../opscenter/api';
  import { t } from '../lib/i18n/index.svelte';
  import AgentChatFrame from '../cplugs/huddle/agents/AgentChatFrame.svelte';
  import type { AgentDrawerTab } from '../cplugs/huddle/agents/agent-page.svelte';

  let { agent }: { agent: number } = $props();
  let tab = $state<AgentDrawerTab>('chat');

  onMount(() => {
    initAuth();
    startEvents();
  });
</script>

{#if auth.state === 'signed-out'}
  <p class="ap-notice" role="status">{t('opscenter.popout.signed_out')}</p>
{:else}
  <section class="ap" data-popout-agent={agent} aria-label={t('cplug.huddle.swarm.drawer.label')}>
    <AgentChatFrame id={agent} bind:tab />
  </section>
{/if}

<style>
  @layer components {
    .ap {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
      background: var(--oc-ground-page);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .ap-notice {
      margin: var(--oc-space-4);
      color: var(--oc-text-muted);
      font: var(--oc-fs-label) var(--font-mono);
      letter-spacing: 0.08em;
    }
  }
</style>
