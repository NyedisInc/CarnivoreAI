import { mountPanel } from '../mount';
import DrawerHeader from './DrawerHeader.svelte';

export const DRAWER_HEADER_ID = 'session-sidebar-header';

export function mountDrawerHeader(): boolean {
    return mountPanel(DRAWER_HEADER_ID, DrawerHeader) !== null;
}
