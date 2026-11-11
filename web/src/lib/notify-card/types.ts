import type { NotifyKind } from './contract.gen';

export interface NotifyCardData {
    strip: [string, string, string];
    agent: string;
    computer: string;
    ts: string;
    answered?: string;
    ask?: string;
    opts?: [string, string, string][];
    multi?: boolean;
    qcount?: number;
    cmd?: string[];
    dir?: string;
    tool?: string;
    name?: string;
    bytes?: number;
    mime?: string;
    from?: string;
    host?: string;
    url?: string;
    title?: string;
    mixed_script?: boolean;
    w?: number;
    h?: number;
    dur?: number;
    caption?: string;
    mins?: number;
    files?: string[];
    stats?: number[][];
    pages?: number;
    nfiles?: number;
    tail?: string[];
    exit?: number;
    to?: string;
    sessions?: string[];
    notes?: string[];
    asker_path?: string;
    positions?: [string, string, string?][];
    text?: string;
    thread?: [string, string][];
    account?: string;
    provider?: string;
    head?: string[];
    reason?: string;
    body?: string;
}

export type NotifyActs = readonly (readonly [string, string])[];

export const KIND_LIGHT: Record<NotifyKind, 'yellow' | 'cyan' | 'green' | 'red' | 'gray'> = {
    yesno: 'yellow', choice: 'yellow', permission: 'yellow', swarm: 'yellow',
    file: 'cyan', link: 'cyan', image: 'cyan', video: 'cyan', update: 'cyan', appupdate: 'cyan', crosstalk: 'cyan',
    finished: 'green', died: 'red', signin: 'red', notice: 'gray',
};
