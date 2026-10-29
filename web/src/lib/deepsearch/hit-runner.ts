import { ApiError } from '../../opscenter/api/auth.svelte';
import { openSession } from '../../cplugs/sdk/sessions.svelte';
import { t } from '../i18n/index.svelte';
import type { ConversationTarget, OpenOutcome } from '../conversation-open/open';
import { bookmarkAt, branchAt, copyText, linkUrl, resumeSession } from './result-actions';
import type { DeepGroup, DeepHit } from './deepsearch-api';
import type { ConvState } from './result-model';

export interface RunnerHost {
  say(line: string): void;
  open(target: ConversationTarget): Promise<OpenOutcome>;
}

const reason = (err: unknown): string => (err instanceof ApiError || err instanceof Error ? err.message : '');

export const targetOf = (g: DeepGroup): ConversationTarget => ({ conversationId: g.conversationId, sessionUuid: g.sessionUuid, projectId: g.projectId });

export class HitRunner {
  #host: RunnerHost;

  constructor(host: RunnerHost) {
    this.#host = host;
  }

  async go(group: DeepGroup, state: ConvState): Promise<boolean> {
    this.#host.say('');
    if ((state !== 'live' && state !== 'asleep') || !group.sessionUuid) return false;
    try {
      if (state === 'asleep') await resumeSession(group.sessionUuid);
      const outcome = await this.#host.open(targetOf(group));
      return outcome === 'switched' || outcome === 'page';
    } catch (err) {
      this.#host.say(t('deepsearch.action.resume_failed', { error: reason(err) }));
      return false;
    }
  }

  async branch(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    this.#host.say('');
    if (!group.sessionUuid || !hit.entryUuid) return false;
    try {
      const made = await branchAt(group.sessionUuid, hit.entryUuid, group.conversationId);
      if (made.sessionId) await openSession(made.sessionId, made.tmuxName);
      return true;
    } catch (err) {
      this.#host.say(t('deepsearch.action.branch_failed', { error: reason(err) }));
      return false;
    }
  }

  async bookmark(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    this.#host.say('');
    if (!group.sessionUuid || !hit.entryUuid) return false;
    try {
      await bookmarkAt(group.sessionUuid, hit.entryUuid);
      this.#host.say(t('deepsearch.action.bookmarked'));
      return true;
    } catch (err) {
      this.#host.say(t('deepsearch.action.bookmark_failed', { error: reason(err) }));
      return false;
    }
  }

  async link(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    this.#host.say('');
    if (hit.line === null) return false;
    const copied = await copyText(linkUrl({ conversationId: group.conversationId, line: hit.line, fileKind: hit.fileKind, hostKey: group.hostKey }));
    this.#host.say(t(copied ? 'deepsearch.action.copied' : 'deepsearch.action.copy_failed'));
    return copied;
  }
}
