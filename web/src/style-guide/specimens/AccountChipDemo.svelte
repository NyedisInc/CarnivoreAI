<script lang="ts">
  import { onDestroy } from 'svelte';
  import AccountMenu from '../../lib/drawer-hud/AccountMenu.svelte';
  import DrawerBar from '../../lib/drawer/DrawerBar.svelte';
  import type { BarView } from '../../lib/drawer/bar-view.svelte';
  import { run } from '../../lib/drawer/bar';
  import { accountChip, closeAccountMenu } from '../../lib/drawer-hud/account-menu.svelte';

  const VERSION = { text: 'v1.13.0', preview: false, previewText: 'preview', href: null };
  const signedIn: BarView = { crown: false, version: VERSION, identity: { kind: 'member', name: 'sam', provider: 'github' } };
  const signedOut: BarView = { crown: false, version: VERSION, identity: { kind: 'lurker', name: '', provider: null } };
  const lit: BarView = { crown: true, version: { ...VERSION, text: 'v1.13.0', preview: true }, identity: { kind: 'member', name: 'sam', provider: 'github' } };
  accountChip.identity = { kind: 'member', name: 'sam', provider: 'github' };

  onDestroy(() => closeAccountMenu());

  function onClick(event: MouseEvent): void {
    const target = event.target as Element | null;
    const btn = target && target.closest ? target.closest('[data-bar-action]') : null;
    if (btn) run(btn.getAttribute('data-bar-action'), btn);
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="sg-grid-2" onclick={onClick}>
  <div class="sg-drawer-host"><DrawerBar view={signedIn} /></div>
  <div class="sg-drawer-host"><DrawerBar view={signedOut} /></div>
  <div class="sg-drawer-host"><DrawerBar view={lit} /></div>
  <div class="sg-rail-host mr-footer"><DrawerBar view={signedIn} /></div>
</div>
<AccountMenu />
