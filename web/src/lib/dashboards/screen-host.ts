import { createOverlayHost } from '../manager-frame/overlay-host';
import DashboardsScreen from './DashboardsScreen.svelte';

export const DASHBOARDS_SCREEN_CONTAINER = 'dashboards-screen';

export const DASHBOARDS_HASH = '#dashboards';

const host = createOverlayHost(DASHBOARDS_SCREEN_CONTAINER, DashboardsScreen, DASHBOARDS_HASH);

export const openDashboardsScreen = (): boolean => host.open();

export const closeDashboardsScreen = (): boolean => host.close();

export const wireDashboardsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
