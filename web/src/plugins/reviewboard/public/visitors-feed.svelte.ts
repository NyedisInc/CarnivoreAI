import { type VisitorRevision } from '../board-visitor-revisions.svelte';
import { resourcePush } from '../../sdk';
import { listVisitors, VISITORS_POLL_MS, visitorsTopic, type VisitorResponse } from './visitors-api';

export interface VisitorsFeed {
  rows: VisitorResponse[];
  visitors: VisitorRevision[];
  viewing: number;
  loaded: boolean;
  error: unknown;
}

export interface VisitorsFollow {
  feed: VisitorsFeed;
  refresh: () => Promise<void>;
  stop: () => void;
}

interface Entry {
  feed: VisitorsFeed;
  followers: number;
  inflight: Promise<void> | null;
  again: boolean;
  unfollow: () => void;
}

const boards = new Map<string, Entry>();

function read(slug: string, entry: Entry): Promise<void> {
  if (entry.inflight) {
    entry.again = true;
    return entry.inflight;
  }
  const run = async (): Promise<void> => {
    do {
      entry.again = false;
      try {
        const answer = await listVisitors(slug);
        entry.feed.rows = answer.responses;
        entry.feed.visitors = answer.visitors.map((row) => ({ ...row, present: answer.present.includes(row.number) }));
        entry.feed.viewing = answer.viewing;
        entry.feed.error = null;
      } catch (error) {
        entry.feed.error = error;
      }
    } while (entry.again);
    entry.feed.loaded = true;
    entry.inflight = null;
  };
  entry.inflight = run();
  return entry.inflight;
}

export function followVisitors(slug: string): VisitorsFollow {
  let entry = boards.get(slug);
  if (!entry) {
    const feed: VisitorsFeed = $state({ rows: [], visitors: [], viewing: 0, loaded: false, error: null });
    const fresh: Entry = { feed, followers: 0, inflight: null, again: false, unfollow: () => {} };
    fresh.unfollow = resourcePush().pushOrPoll(() => void read(slug, fresh), VISITORS_POLL_MS, [visitorsTopic(slug)]);
    void read(slug, fresh);
    boards.set(slug, fresh);
    entry = fresh;
  }
  const mine = entry;
  mine.followers += 1;
  let stopped = false;
  return {
    feed: mine.feed,
    refresh: () => read(slug, mine),
    stop: () => {
      if (stopped) return;
      stopped = true;
      mine.followers -= 1;
      if (mine.followers > 0) return;
      mine.unfollow();
      boards.delete(slug);
    },
  };
}
