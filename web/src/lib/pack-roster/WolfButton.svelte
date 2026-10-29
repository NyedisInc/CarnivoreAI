
<script lang="ts">
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import IconButton from '../base/IconButton.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import { makeMaster } from '../pack-machines/pack-machines-store.svelte';
  import { canLead, type RosterComputer } from './roster-model';

  const { c }: { c: RosterComputer } = $props();

  async function lead(event: MouseEvent): Promise<void> {
    event.stopPropagation();
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string; calm: boolean }>(FedConfirmModal, {
      title: t('roster.lead.button'), body: t('roster.lead.body', { name: c.name }), confirmLabel: t('roster.lead.confirm'), calm: true,
    });
    if (yes) await makeMaster(c.id);
  }
</script>

{#if canLead(c)}
  <IconButton label={`${t('roster.lead.button')} ${c.name}`} icon="wolf" iconSize={14} data-roster-key="leader" data-act="makeleader" onclick={lead} />
{/if}
