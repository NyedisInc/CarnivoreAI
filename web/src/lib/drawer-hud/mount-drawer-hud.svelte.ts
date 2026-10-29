/* plugin bar indicators the account chip the bottom bar */
import { untrack } from 'svelte';
import { mountPanel } from '../mount';
import AccountMenu from './AccountMenu.svelte';
import { paint as paintBar } from '../drawer/bar';
import { accountChip } from './account-menu.svelte';
import { followCatalogAccount } from './catalog-account.svelte';
import { cplugBarIndicators } from '../../cplugs/host/readers';
import { startSwarmSwitch } from '../swarm-switch/control.svelte';
import { beastIndicator, startBeastStatus } from '../beast-mode/control.svelte';

export const ACCOUNT_MENU_ID = 'session-sidebar-account-menu';

let stopLight: (() => void) | null = null;
let stopAccount: (() => void) | null = null;

export function mountDrawerHud(): boolean {
    if (typeof document === 'undefined' || typeof document.getElementById !== 'function') return false;
    const menu = document.getElementById(ACCOUNT_MENU_ID) ? mountPanel(ACCOUNT_MENU_ID, AccountMenu) : null;
    startSwarmSwitch();
    startBeastStatus();
    if (!stopAccount) stopAccount = followCatalogAccount();
    if (!stopLight) {
        stopLight = $effect.root(() => {
            $effect(() => {
                void accountChip.identity;
                if (beastIndicator.visible()) void beastIndicator.label();
                for (const item of cplugBarIndicators()) void item.label();
                untrack(() => paintBar());
            });
        });
    }
    return menu !== null;
}
