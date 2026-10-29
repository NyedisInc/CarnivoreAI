<script lang="ts">
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { t } from '../i18n/index.svelte';
    import { layoutEntry, masterAllOn, run } from '../drawer/bar';
  import { accountChip, accountMenu, closeAccountMenu } from './account-menu.svelte';
  import { closeDrawerAfterSwitch } from '../drawer-tabs/menu-hotkeys';
  import { accountFacts } from '../carnivore-account/account-store.svelte';
  import { openSignInDoor, signOutOfAccount } from '../carnivore-account/sign-in-door';
  import { cplugAccountMenuItems } from '../../cplugs/host/readers';
  import { swarmSwitch, toggleSwarm } from '../swarm-switch/control.svelte';
  import { beastMenuItem } from '../beast-mode/control.svelte';

  function app(): { logout?: () => void } | null {
    return (globalThis as { App?: { logout?: () => void } }).App ?? null;
  }

  function signIn(): void {
    const anchor = accountMenu.anchor;
    closeAccountMenu();
    anchor?.focus();
    openSignInDoor('menu');
  }

  function openAccountPage(): void {
    const anchor = accountMenu.anchor;
    closeAccountMenu();
    anchor?.focus();
    (globalThis as { CloudeWeb?: { openAccountScreen?: () => boolean } }).CloudeWeb?.openAccountScreen?.();
    closeDrawerAfterSwitch();
  }

  let flips = $state(0);

  function barAction(action: string): () => void {
    return () => {
      const anchor = accountMenu.anchor;
      closeAccountMenu();
      anchor?.focus();
      run(action, anchor);
    };
  }

  function nodes(): MenuNode[] {
    void flips;
    const member = accountChip.identity?.kind === 'member';
    const out: MenuNode[] = [];
    if (member) out.push({ id: 'account_page', label: t('account.menu.account'), icon: 'person', run: openAccountPage });
    else out.push({ id: 'signin', label: t('account.menu.signin'), icon: 'person', run: signIn });
    const layout = layoutEntry();
    if (layout) {
      out.push({
        id: 'layout',
        label: t(layout.active ? 'layout_editor.bar.done' : 'layout_editor.bar.open'),
        icon: 'layout',
        ...(layout.available ? { run: barAction('layout') } : { blocked: t('drawer.account.layout_blocked') }),
      });
    }
    const master = masterAllOn();
    if (master !== null) {
      out.push({
        id: 'master_all',
        label: t('header.master_all'),
        icon: 'crown',
        toggle: true,
        checked: master,
        sep: true,
        keepOpen: true,
        run: () => {
          run('master_all', accountMenu.anchor);
          flips += 1;
        },
      });
    }
    const swarm = swarmSwitch.data;
    if (swarm) {  //  hidden 
      out.push({
        id: 'swarm',
        label: t('drawer.account.swarm'),
        icon: 'bot',
        title: t('drawer.account.swarm_title'),
        toggle: true,
        checked: swarm.enabled,
        keepOpen: true,
        ...(master === null ? { sep: true } : {}),
        run: () => void toggleSwarm(),
      });
    }
    const anchorNow = accountMenu.anchor;
    const close = (): void => {
      closeAccountMenu();
      anchorNow?.focus();
    };
    out.push({
      id: beastMenuItem.id,
      label: beastMenuItem.label(),
      icon: beastMenuItem.icon,
      toggle: true,
      checked: beastMenuItem.checked?.() === true,
      sep: master === null && !swarm,
      run: () => beastMenuItem.run({ close, anchor: anchorNow }),
    });
    for (const item of cplugAccountMenuItems()) {
      const checked = item.checked?.();
      out.push({
        id: `cplug.${item.cplugId}.${item.id}`,
        label: item.label(),
        icon: item.icon,
        ...(checked === undefined ? {} : { toggle: true, checked }),
        run: () => item.run({ close, anchor: anchorNow }),
      });
    }
    if (member) {
      out.push({
        id: 'signout',
        label: t('account.menu.signout'),
        icon: 'log-out',
        sep: true,
        run: () => {
          closeAccountMenu();
          void signOutOfAccount();
        },
      });
    }
    out.push({
      id: 'logout',
      label: t('drawer.account.logout'),
      icon: 'lock',
      sep: true,
      run: () => {
        closeAccountMenu();
        app()?.logout?.();
      },
    });
    return out;
  }

  const root = $derived<MenuNode[]>(accountMenu.open ? nodes() : []);
  const heading = $derived.by(() => {
    const who = accountChip.identity;
    return who?.kind === 'member' ? who.name : t('drawer.account.lurker_hint');
  });
  const subheading = $derived(accountChip.identity?.kind === 'member' ? (accountFacts()?.email ?? '') : '');
</script>

{#if accountMenu.open}
  <CascadeMenu {root} anchor={accountMenu.anchor} label={t('drawer.account.menu')} {heading} {subheading} above={!accountMenu.anchor?.closest('.oc-topbar')} onClose={closeAccountMenu} />
{/if}
