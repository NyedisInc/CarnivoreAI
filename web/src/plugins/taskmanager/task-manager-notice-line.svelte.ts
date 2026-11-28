import type { Attachment } from 'svelte/attachments';
import { t } from '../sdk';
import { reopenPick, sendPicks } from './huddle-send-many.svelte';
import { answerRefusalShown, clearAnswerRefusal, settleAnswerRefusal } from './ask/ask-notice.svelte';

export interface NoticeKey {
  'data-task-manager-notice-pick'?: '';
  'data-task-manager-notice-dismiss'?: '';
  title?: string;
  onclick: () => void;
}

export function noticeClickable(): boolean {
  return !!sendPicks.reopen?.length || answerRefusalShown();
}

export function noticeKey(): NoticeKey {
  if (sendPicks.reopen?.length) return { 'data-task-manager-notice-pick': '', onclick: reopenPick };
  return { 'data-task-manager-notice-dismiss': '', title: t('cplug.huddle.ask.refused.dismiss'), onclick: clearAnswerRefusal };
}

export const settleNotice: Attachment = (_node) => {
  settleAnswerRefusal();
};
