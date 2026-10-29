import manifest from '../../../../src/cplugs/reviewboard/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';
import { ApiError, authFetch, cplugEnabled, registerPostedPageOpener, registerProjectPanel, registerRoundOpener } from '../sdk';
import { openRound } from './board-api';
import { reviewboardTab } from './board-tab';
import ClosedReviews from './ClosedReviews.svelte';

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
  id: 'reviewboard', manifest: manifest as CplugManifest, tabs: [reviewboardTab], start: () => {
    registerRoundOpener(openRound);
    registerPostedPageOpener(openPosted);
    registerProjectPanel({
      id: CLOSED_PANEL_ID, labelKey: 'cplug.reviewboard.closed.group', hintKey: 'cplug.reviewboard.closed.hint', component: ClosedReviews,
      enabled: () => cplugEnabled(reviewboardCplug.manifest),
    });
  },
};
