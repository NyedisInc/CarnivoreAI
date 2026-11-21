
<script lang="ts">
  import { announceFailure, promptText, t } from '../../sdk';
  import { CascadeMenu } from '../../sdk/ui';
  import { refreshRoster } from '../agents/agent-roster.svelte';
  import { renameAgent } from '../chat/chat-api';
  import { nodeMenuTree, patchLook, type LookPatch } from './node-menu';
  import type { PanelAgent } from './panel-state';

  let { agent, label, anchor, onClose }: { agent: PanelAgent; label: string; anchor: HTMLElement; onClose: () => void } = $props();

  let status = $state('');

  function reason(error: unknown): string {
    const detail = (error as { detail?: unknown })?.detail;
    return t('cplug.huddle.swarm.node_menu.failed', { reason: typeof detail === 'string' ? detail : String((error as Error)?.message ?? error) });
  }

  async function patch(body: LookPatch): Promise<void> {
    try {
      await patchLook(agent.id, body);
      onClose();
      await refreshRoster();
    } catch (error) {
      status = reason(error);
    }
  }

  async function rename(): Promise<void> {
    onClose();
    const next = (await promptText({
      title: t('leader.rename.title'), label: t('leader.rename.label'), defaultValue: label,
      confirmLabel: t('leader.rename.save'), cancelLabel: t('leader.confirm.cancel'),
    }))?.trim();
    if (!next || next === label) return;
    try {
      await renameAgent(agent.id, next);
      await refreshRoster();
    } catch (error) {
      announceFailure(reason(error));
    }
  }

  const above = anchor.getBoundingClientRect().top > window.innerHeight / 2;

  const root = $derived(nodeMenuTree(agent, { rename: () => void rename(), patch: (body) => void patch(body) }));
</script>

<CascadeMenu {root} {anchor} label={t('cplug.huddle.swarm.node_menu.label', { name: label })} {status} {above} {onClose} />
