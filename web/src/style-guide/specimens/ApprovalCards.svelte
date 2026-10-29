<script lang="ts">
  import ApprovalCard from '../../lib/approvals/ApprovalCard.svelte';
  import type { ApprovalItem } from '../../lib/approvals/approvals-model';
  import samples from '../approval-specimens.json';

  type Sample = (typeof samples)[number];

  const GROUPS: { id: string; label: string }[] = [
    { id: 'destructive', label: 'destructive: approve in the danger token' },
    { id: 'changes', label: 'changes: approve in the confirm token' },
    { id: 'calm', label: 'calm: small, reversible, or a generic card' },
  ];

  function toItem(sample: Sample): ApprovalItem {
    const { input } = sample;
    return {
      id: `sg-ap-${sample.id}`, source: 'agent_action', session_id: '', action: input.action, caller: sample.caller,
      summary: input.summary, confirm_text: input.confirm_text || undefined,
      display: sample.display,
    } as ApprovalItem;
  }
</script>

<div class="pledger sg-ap">
  {#each GROUPS as group (group.id)}
    <p class="pl-label sg-ap__group">{group.label}</p>
    {#each samples.filter((s) => s.group === group.id) as sample (sample.id)}
      <p class="sg-ap__kind">{sample.label}</p>
      <ApprovalCard item={toItem(sample)} onJump={() => {}} />
    {/each}
  {/each}
</div>

<style>
  @layer components {
    .sg-ap__group {
      margin: var(--oc-space-4) 0 var(--oc-space-1);
    }
    .sg-ap__kind {
      margin: var(--oc-space-3) 0 var(--oc-space-1);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
    }
  }
</style>
