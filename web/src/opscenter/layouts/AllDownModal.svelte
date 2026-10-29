
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../../lib/launchpad/ModalShell.svelte';
    import { t } from '../../lib/i18n/index.svelte';
    import { asleep, recent, sessions } from '../api';
    import MemberDownRow from './MemberDownRow.svelte';
    import type { SavedLayout } from './api';

    interface Props {
        layout: SavedLayout;
        close: (value: boolean | null) => void;
    }

    let { layout, close }: Props = $props();

    const members = $derived([...layout.members].sort((a, b) => a.position - b.position));

    onMount(() => {
        void asleep.refresh(true);
        void recent.refresh(true);
    });

    $effect(() => {
        const rows = sessions.data;
        if (!rows) return;
        const rowIds = new Set(members.map((member) => member.session_row_id));
        if (rows.some((row) => typeof row.session_row_id === 'number' && rowIds.has(row.session_row_id))) {
            close(true);
        }
    });
</script>

<ModalShell title={layout.name} overlayClass="text-prompt-modal" onCancel={() => close(false)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {layout.name}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')}
                onclick={() => close(false)}>&times;</button>
        </div>
    {/snippet}
    <div class="lad-body" data-all-down-modal>
        <p class="lad-hint">{t('layout.all_down.hint')}</p>
        {#each members as member (member.session_row_id)}
            <div class="lad-row">
                <MemberDownRow {member} />
            </div>
        {/each}
    </div>
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" onclick={() => close(false)}
            >{t('layout.all_down.close')}</button
        >
    {/snippet}
</ModalShell>

<style>
  @layer components {
      .lad-body {
          display: flex;
          flex-direction: column;
          gap: var(--oc-space-1);
          max-height: 60vh;
          overflow-y: auto;
      }

      .lad-hint {
          margin: 0 0 var(--oc-space-1);
          color: var(--oc-text-dim);
          font-size: var(--oc-fs-label);
      }

      .lad-row {
          border-top: 1px solid var(--oc-line-faint);
      }

      .lad-row:first-child {
          border-top: none;
      }
  }
</style>
