<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import type { DeepGroup } from './deepsearch-api';
  import { isRemote, type ConvState } from './result-model';

  const BUNDLE_ID_CHARS = 12;

  interface Props {
    group: DeepGroup;
    conv: ConvState;
  }
  let { group, conv }: Props = $props();

  const bundle = $derived(group.exported ? (group.exported.label ?? group.exported.bundleId.slice(0, BUNDLE_ID_CHARS)) : '');

  const host = $derived(
    isRemote(group) ? (group.hostLabel ?? group.hostKey ?? '') : group.alsoOn.length > 0 ? t('deepsearch.also_on', { computers: group.alsoOn.join(', ') }) : '',
  );
</script>

{#if conv === 'backup'}
  <span class="dps__tag dps__tag--backup" title={t('deepsearch.tag.backup_tip')} data-testid="deepsearch-from-backup">{t('deepsearch.tag.backup')}</span>
{/if}
{#if group.exported}
  <span class="dps__tag dps__tag--exported" title={t(group.exported.localRemoved ? 'deepsearch.tag.exported_removed_tip' : 'deepsearch.tag.exported_tip')} data-testid="deepsearch-exported">{t('deepsearch.tag.exported', { bundle })}</span>
{/if}
{#if host}<span class="dps__tag dps__host" data-testid="deepsearch-host">{host}</span>{/if}
