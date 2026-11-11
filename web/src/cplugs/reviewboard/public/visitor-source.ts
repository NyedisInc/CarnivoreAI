import { registerVisitorRevisionSource, type VisitorRevisionFollow } from '../board-visitor-revisions.svelte';
import { publicLinksOn } from './public-links-on';
import { visitorAnswers } from './visitors-api';
import { followVisitors } from './visitors-feed.svelte';

export function followBoardVisitors(slug: string): VisitorRevisionFollow {
  const follow = followVisitors(slug);
  return { rows: () => follow.feed.visitors, answers: (revision, number) => visitorAnswers(slug, revision, number), stop: follow.stop };
}

export function registerVisitorSource(): void {
  registerVisitorRevisionSource({ id: 'reviewboard.visitors', enabled: publicLinksOn, follow: followBoardVisitors });
}
