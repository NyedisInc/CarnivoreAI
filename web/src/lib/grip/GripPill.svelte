<script lang="ts" module>
  export const CLICK_SLOP_PX = 4;
</script>

<script lang="ts">
  let { axis = 'x', ...rest }: { axis?: 'x' | 'y'; [key: string]: unknown } = $props();
</script>

<span class="oc-grip" data-axis={axis} {...rest}></span>

<style>
  @layer components {
    .oc-grip {
      display: block;
      flex: none;
      width: 24px;
      height: 2px;
      border-radius: 1px;
      background: var(--grip-color, var(--oc-line-panel));
    }

    .oc-grip[data-axis='y'] {
      width: 2px;
      height: 24px;
    }
  }
</style>
