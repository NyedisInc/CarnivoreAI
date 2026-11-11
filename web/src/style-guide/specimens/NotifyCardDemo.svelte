<script lang="ts">
  import NotifyCard from '../../lib/notify-card/NotifyCard.svelte';
  import { choice, choiceActs, permission, permissionActs, permissionBody } from './fixtures/notify-card';
</script>

<div style="display: flex; flex-wrap: wrap; gap: var(--oc-space-4)">
  <div style="width: 344px; max-width: 100%"><NotifyCard card={permission} kind="permission" body={permissionBody} acts={permissionActs} /></div>
  <div style="width: 344px; max-width: 100%"><NotifyCard card={choice} kind="choice" acts={choiceActs} /></div>
  <div style="width: 344px; max-width: 100%"><NotifyCard card={{ ...permission, answered: 'computer' }} kind="permission" /></div>
</div>
