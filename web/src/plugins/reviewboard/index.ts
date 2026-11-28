import manifest from '../../../../src/plugins/reviewboard/carnivore.toml';
import type { CplugManifest, CplugWeb } from '../sdk';
import { ApiError, authFetch, cplugEnabled, lazyComponent, registerPageRowAction, registerPostedPageOpener, registerBoardAttachments, registerProjectPanel, unregisterBoardAttachments, registerRoundOpener } from '../sdk';
import { boardCardSource, openRound } from './board-api';
import { reviewboardTab } from './board-tab';
import { sharePageRowAction } from './public/page-row-action';
import { publicLinksOn } from './public/public-links-on';

const ClosedReviews = lazyComponent(() => import('./ClosedReviews.svelte'));

export const CLOSED_PANEL_ID = 'reviewboard.closed';

async function openPosted(page: { item: number; title: string }): Promise<boolean> {
  try {
    await authFetch('/cplugs/reviewboard/posted/open', { method: 'POST', body: JSON.stringify(page) });
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return false;
    throw err;
  }
}

export const reviewboardCplug: CplugWeb = {
  id: 'reviewboard', manifest: manifest as CplugManifest, tabs: [reviewboardTab], stop: unregisterBoardAttachments, start: () => {
    const on = (): boolean => cplugEnabled(reviewboardCplug.manifest);
    registerRoundOpener(openRound, on);
    registerBoardAttachments(boardCardSource, on);
    registerPostedPageOpener(openPosted, on);
    registerProjectPanel({
      id: CLOSED_PANEL_ID, labelKey: 'cplug.reviewboard.closed.group', hintKey: 'cplug.reviewboard.closed.hint', component: ClosedReviews,
      enabled: on,
    });
    registerPageRowAction(sharePageRowAction(publicLinksOn));
  },
};
