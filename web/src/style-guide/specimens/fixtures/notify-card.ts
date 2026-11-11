import type { NotifyCardData } from '../../../lib/notify-card/types';

const strip = (word: string, agent: string, computer: string): [string, string, string] => [word, agent, computer];

export const permission: NotifyCardData = { strip: strip('permission', 'cloudecode-2', 'studio'), agent: 'cloudecode-2', computer: 'studio', ts: '9:41', cmd: ['cd web && npm run build'], dir: 'web/', tool: 'bash' };
export const choice: NotifyCardData = {
    strip: strip('pick one', 'billing-5', 'nostromo'), agent: 'billing-5', computer: 'nostromo', ts: '9:41', ask: 'which plan should I build: A, B or C?',
    opts: [['a', 'plan a', 'patch the widget engine in place, smallest diff, 1 file'], ['b', 'plan b', 'split the engine into two modules, 4 files, one new test']],
};
export const permissionActs = [['opt.1', 'allow'], ['opt.2', 'deny']] as const;
export const choiceActs = [['opt.1', 'plan a'], ['opt.2', 'plan b'], ['reply', 'type an answer']] as const;
export const permissionBody = 'npm run build in web/';
