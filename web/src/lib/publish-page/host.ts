import { browserPublishHost, type PublishHost, type SubmissionReport } from '../catalog/publish';
import { fetchFacts } from './api-facts';
import { fetchLimits, fetchRules, postAppeal, postWithdraw } from './api-author';
import { fetchMine } from './api';
import type { Facts, Limits, Rules, SubRow } from './types';

export interface PageHost extends PublishHost {
    mine(force?: boolean): Promise<SubRow[]>;
    limits(): Promise<Limits>;
    rules(): Promise<Rules>;
    facts(location: string): Promise<Facts>;
    appeal(id: string, text: string): Promise<void>;
    withdraw(id: string): Promise<void>;
    report(id: string): Promise<SubmissionReport>;
}

export function browserPageHost(): PageHost {
    const base = browserPublishHost();
    return {
        ...base,
        mine: (force = false) => fetchMine(force),
        limits: fetchLimits,
        rules: fetchRules,
        facts: fetchFacts,
        appeal: postAppeal,
        withdraw: postWithdraw,
        report: (id) => base.submissionReport(id),
    };
}
