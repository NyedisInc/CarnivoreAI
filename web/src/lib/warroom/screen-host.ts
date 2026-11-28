import { createOverlayHost } from '../manager-frame/overlay-host';

export const WARROOM_SCREEN_CONTAINER = 'warroom-screen';
export const WARROOM_HASH = '#warroom';

const warroomHost = createOverlayHost(WARROOM_SCREEN_CONTAINER, { load: () => import('./WarRoomScreen.svelte') }, WARROOM_HASH);

export const openWarroomScreen = (): boolean => warroomHost.open();

export const closeWarroomScreen = (): boolean => warroomHost.close();

export function wireWarroomDeepLink(target?: Window | null): () => void {
    return warroomHost.wireDeepLink(target);
}
