<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { DIM_MAX, DIM_MIN, setCellDim, storedCellDim } from './cell-dim';

  let percent = $state(storedCellDim());
</script>

<label class="cdim">
  <input
    class="cdim__range"
    type="range"
    min={DIM_MIN}
    max={DIM_MAX}
    step="5"
    aria-label={t('settings.item.cell_dim.label')}
    bind:value={percent}
    oninput={() => setCellDim(percent)}
  />
  <span class="cdim__value">{percent}%</span>
</label>

<style>
  @layer components {
    .cdim {
      display: flex;
      align-items: center;
      gap: var(--oc-space-3);
      min-width: 0;
    }

    .cdim__range {
      flex: 1;
      min-width: 0;
      accent-color: var(--oc-coral);
    }

    .cdim__value {
      flex: none;
      min-width: 34px;
      text-align: right;
      font-family: var(--font-mono);
    }
  }
</style>
