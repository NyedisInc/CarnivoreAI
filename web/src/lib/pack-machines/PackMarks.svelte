
<script lang="ts">
  import './pack-machines.css';
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import type { LinkState } from './pack-meter-math';

  interface Props {
    alpha?: boolean;
    self?: boolean;
    link?: LinkState | null;
    tips?: boolean;
    size?: number;
  }
  const { alpha = false, self = false, link = null, tips = true, size }: Props = $props();
</script>

<span class="pk-marks">
  {#if alpha}<span class="pm-badge" data-pm="master">{t('pack.machines.master')}</span>{/if}
  {#if self}
    <span class="pk-icon pk-icon--self" data-mark="self" role="img" aria-label={t('pack.machines.this_machine')} title={tips ? t('pack.machines.this_machine') : undefined}>
      <Icon name="computer" size={size ?? 16} />
    </span>
  {/if}
  {#if link}
    <span class="pk-icon pk-icon--{link}" data-mark="link" data-link={link} role="img" aria-label={t(`pack.link.${link}`)} title={tips ? t(`pack.link.${link}`) : undefined}>
      <Icon name={link === 'down' ? 'computers-broken' : 'computers-linked'} size={size ?? 18} />
    </span>
  {/if}
</span>

<style>
  .pk-marks { display: inline-flex; align-items: center; gap: 8px; }
  .pk-icon { display: inline-flex; align-items: center; }
  .pk-icon--self, .pk-icon--linked { color: var(--oc-green); }
  .pk-icon--connecting { color: var(--oc-yellow); }
  .pk-icon--down { color: var(--oc-text-muted); }
  .pk-icon--error { color: var(--oc-coral); }
</style>
