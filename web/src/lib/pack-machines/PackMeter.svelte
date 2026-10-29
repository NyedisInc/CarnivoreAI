
<script lang="ts">
  import { METER_CELLS, filledCells, levelOf, reserveCells } from './pack-meter-math';

  interface Props {
    label: string;
    pct: number | null;
    text: string;
    reservePct?: number | null;
    title: string;
    small?: boolean;
    tip?: boolean;
  }
  const { label, pct, text, reservePct = null, title, small = false, tip = true }: Props = $props();

  const lit = $derived(filledCells(pct));
  const held = $derived(reserveCells(reservePct));
</script>

<span class="pk-meter" class:pk-meter--sm={small} data-level={pct === null ? 'none' : levelOf(pct)} role="img" aria-label={title} title={tip ? title : undefined}>
  <span class="pk-meter__label">{label}</span>
  <span class="pk-meter__bar">
    {#each Array.from({ length: METER_CELLS }, (_, i) => i) as i (i)}
      <span class="pk-meter__cell" data-on={i < lit ? '1' : '0'} data-held={i >= METER_CELLS - held ? '1' : '0'}></span>
    {/each}
  </span>
  <span class="pk-meter__value">{text}</span>
</span>

<style>
  .pk-meter {
    display: grid;
    grid-template-columns: 3.4em minmax(6rem, 14rem) minmax(4.5em, auto);
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
    --pk-fill: var(--oc-green);
  }
  .pk-meter--sm { grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px; }
  .pk-meter--sm .pk-meter__bar { gap: 0; }
  .pk-meter--sm .pk-meter__label, .pk-meter--sm .pk-meter__value { font-size: 8.5px; }
  .pk-meter--sm .pk-meter__label { letter-spacing: 0.04em; text-transform: none; }
  .pk-meter--sm .pk-meter__bar { height: 7px; }
  .pk-meter[data-level='high'] { --pk-fill: var(--oc-yellow); }
  .pk-meter[data-level='critical'] { --pk-fill: var(--oc-coral); }
  .pk-meter[data-level='none'] { --pk-fill: var(--oc-text-muted); }
  .pk-meter__label {
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--oc-text-secondary);
  }
  .pk-meter__bar {
    display: flex;
    gap: 1px;
    height: 9px;
    padding: 1px;
    box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    border-radius: 2px;
  }
  .pk-meter__cell {
    flex: 1 1 0;
    border-radius: 1px;
  }
  .pk-meter__cell[data-held='1'] {
    background: repeating-linear-gradient(135deg, var(--oc-text-muted) 0 1px, transparent 1px 3px);
    opacity: 0.7;
  }
  .pk-meter__cell[data-on='1'] {
    background: var(--pk-fill);
    opacity: 1;
  }
  .pk-meter__value {
    font-size: 11px;
    color: var(--oc-text-primary);
    white-space: nowrap;
  }
</style>
