
<script lang="ts">
  interface Props {
    size?: number;
    label?: string;
  }
  let { size = 14, label = '' }: Props = $props();
</script>

<svg class="sbcal-back" width={size} height={size} viewBox="0 0 14 14" role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : 'true'}>
  <circle cx="7" cy="7" r="5.5" />
  <path d="M8.6 4.6 L5 7 L8.6 9.4" />
</svg>

<style>
  @layer components {
    .sbcal-back {
      flex: none;
      fill: none;
      stroke: var(--oc-coral);
      stroke-width: 1.5;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
  }
</style>
