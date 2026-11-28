import { createOverlayHost } from '../manager-frame/overlay-host';

export const LOGS_SCREEN_CONTAINER = 'logs-screen';
export const LOGS_HASH = '#logs';

const logsHost = createOverlayHost(LOGS_SCREEN_CONTAINER, { load: () => import('./LogsScreen.svelte') }, LOGS_HASH);

export const openLogsScreen = (): boolean => logsHost.open();

export const closeLogsScreen = (): boolean => logsHost.close();

export function wireLogsDeepLink(target?: Window | null): () => void {
    return logsHost.wireDeepLink(target);
}
