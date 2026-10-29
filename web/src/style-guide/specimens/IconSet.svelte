<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { icons } from '../../opscenter/ui/icons';

  const names = Object.keys(icons).sort();
</script>

<ul class="sg-icon-grid">
  {#each names as name (name)}
    <li class="sg-icon-cell">
      <span class="sg-icon-row">
        <Icon {name} size={14} />
        <Icon {name} size={16} />
        <Icon {name} size={20} />
      </span>
      <code>{name}</code>
    </li>
  {/each}
</ul>
