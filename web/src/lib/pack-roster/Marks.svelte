
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import type { RosterComputer } from './roster-model';

  const { c }: { c: RosterComputer } = $props();
  const hasLink = $derived(!c.isSelf && c.kind !== 'ssh-only' && c.entry !== null);
  const up = $derived(c.dial === 'linked' || c.dial === 'dialing');
</script>

<span class="pp-marks">
  {#if c.isAlpha}<span class="rs-leader" data-mark="leader" role="img" aria-label={t('roster.mark.leader')}><Icon name="wolf" size={14} /></span>{/if}
  {#if c.isSelf}<span class="rs-self" data-mark="self" role="img" aria-label={t('roster.mark.self')}><Icon name="computer" size={14} /></span>{/if}
  {#if hasLink}<span class={up ? 'rs-link' : 'rs-leader'} data-mark={up ? 'link' : 'linkdown'} role="img" aria-label={up ? t('roster.mark.linked') : t('roster.mark.linkdown')}><Icon name={up ? 'computers-linked' : 'computers-broken'} size={14} /></span>{/if}
</span>
