<script lang="ts">
  import Icon from '../ui/Icon.svelte';
  import { t } from '../../lib/i18n/index.svelte';
</script>

<span class="oc-head-lock" data-head-lock="" role="img" aria-label={t('opscenter.frame.locked')} title={t('opscenter.frame.locked')}>
  <Icon name="lock" size={13} />
</span>

<style>
  @layer components {
    .oc-head-lock {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      color: var(--oc-locked);
      font-size: var(--oc-fs-title);
    }

    .oc-head-lock :global(svg) {
      width: 1em;
      height: 1em;
    }
  }
</style>
