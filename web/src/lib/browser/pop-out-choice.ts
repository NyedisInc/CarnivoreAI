import { browserPath } from '../../popout/popout';
import { t } from '../i18n/index.svelte';
import { openModal } from '../modal';
import type { BrowserInfo } from './api.svelte';
import { openTab } from './pop-out';
import { realPageReach } from './pop-out-reach';
import PopOutChoice from './PopOutChoice.svelte';

export type PopOutChoiceTaken = 'proxy' | 'real';

let asking: { id: string; answer: Promise<PopOutChoiceTaken | null> } | null = null;

/* a dialog is open */
export function askProxyPopOut(
    browser: Pick<BrowserInfo, 'id' | 'label' | 'url'>,
    liveUrl: string | null,
    win: Window = window,
): Promise<PopOutChoiceTaken | null> {
    if (asking) return asking.id === browser.id ? asking.answer : Promise.resolve(null);
    const live = typeof liveUrl === 'string' && liveUrl !== '' && liveUrl !== 'about:blank';
    const answer = openModal(PopOutChoice, {
        label: browser.label || t('browser.page'),
        proxyUrl: browserPath(browser.id),
        reach: realPageReach(live ? liveUrl : browser.url, win.location?.hostname ?? ''),
        shortened: !live,
        openTab: (url: string) => {
            openTab(url, win);
        },
    });
    const held = { id: browser.id, answer };
    asking = held;
    const release = (): void => {
        if (asking === held) asking = null;
    };
    answer.then(release, release);
    return answer;
}
