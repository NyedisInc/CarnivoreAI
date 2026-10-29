
<script lang="ts">
  import StatusLed from '../StatusLed.svelte';
  import AgentMarks from './AgentMarks.svelte';
  import { faceFacts, showsStatusLight, type AgentMarkFacts, type FaceOptions, type FaceRow } from './agent-marks';

  interface Props {
    row?: FaceRow;
    facts?: AgentMarkFacts;
    lifecycle?: FaceOptions['lifecycle'];
    transport?: FaceOptions['transport'];
    bare?: boolean;
    size?: string | null;
    mark?: boolean;
    name?: string;
    nameClass?: string;
  }

  let { row, facts, lifecycle, transport, bare = false, size = null, mark = false, name, nameClass }: Props = $props();

  const read = $derived<AgentMarkFacts>(facts ?? faceFacts(row ?? {}, { lifecycle, transport }));
</script>


{#snippet lamp()}{#if showsStatusLight(read.family)}<StatusLed {bare} {size} status={read.status} unread={read.unread} startupGate={read.startupGate} statusSource={read.statusSource} activityHint={read.activityHint} parkedSummary={read.parkedSummary ?? null} usageLimit={read.usageLimit ?? null} hostOffline={read.hostOffline ?? null} transport={read.transport} />{/if}{/snippet}
{#if mark}<AgentMarks family={read.family}>{#snippet light()}{@render lamp()}{/snippet}</AgentMarks>{:else}{@render lamp()}{/if}{#if name !== undefined}<span class={nameClass}>{name}</span>{/if}
