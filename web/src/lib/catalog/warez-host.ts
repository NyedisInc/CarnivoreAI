/* the warez menu */
import { createOverlayHost } from '../manager-frame/overlay-host';
import WarezScreen from './WarezScreen.svelte';
import type { MenuNode } from './menu/route';
import { openEliteScreen } from '../elite/elite-host';
import { firstVisit, markEliteSeen, settleFirstVisit } from '../elite/first-visit';

export const WAREZ_SCREEN_CONTAINER = 'warez-screen';

export const WAREZ_HASH = '#warez';

export interface WarezOpenOptions {
    kind?: string;
    item?: string;
    node?: MenuNode;
    home?: boolean;
}

const host = createOverlayHost(WAREZ_SCREEN_CONTAINER, WarezScreen, WAREZ_HASH, { aliases: ['#catalog'] });

export const openWarezScreen = (options: WarezOpenOptions = {}): boolean => {
    if (Object.keys(options).length === 0) {
        const view = firstVisit();
        if (view === 'elite') {
            void markEliteSeen();
            return openEliteScreen();
        }
        if (view === 'wait') {
            void settleFirstVisit().then((settled) => {
                if (settled === 'elite') {
                    void markEliteSeen();
                    openEliteScreen();
                } else host.open({});
            });
            return true;
        }
    }
    return host.open({ ...options });
};

export const closeWarezScreen = (): boolean => host.close();

export const isWarezHash = (hash: string | null | undefined): boolean => host.isHash(hash);
