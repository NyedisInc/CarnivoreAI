import type {
    AttachableSession,
    ProjectAuthority,
    ProjectPresencePayload,
    ProjectRow,
    SessionListItem,
    SessionRecord,
} from './types';
import { legacyApi } from '../legacy-globals';

export interface SessionHost {
    getProjects(includeArchived: boolean): Promise<ProjectRow[]>;
    getProjectsPresence(): Promise<ProjectPresencePayload>;
    getProjectsAuthority(): Promise<ProjectAuthority>;
    listAttachableSessions(): Promise<AttachableSession[]>;
    listSessions?(): Promise<SessionListItem[]>;
    getCurrentSession(): Promise<SessionListItem | null>;
    listSessionRecords(): Promise<SessionRecord[]>;
}

interface LegacyApi {
    getProjects(includeArchived: boolean): Promise<ProjectRow[]>;
    getProjectsPresence(): Promise<ProjectPresencePayload>;
    getProjectsAuthority(): Promise<ProjectAuthority>;
    listAttachableSessions(): Promise<AttachableSession[]>;
    listSessions?(): Promise<SessionListItem[]>;
    getCurrentSession(): Promise<SessionListItem | null>;
    listSessionRecords(): Promise<SessionRecord[]>;
}

export function browserSessionHost(): SessionHost {
    const api = (): LegacyApi =>
        legacyApi<LegacyApi>();
    const host: SessionHost = {
        getProjects: (includeArchived) => api().getProjects(includeArchived),
        getProjectsPresence: () => api().getProjectsPresence(),
        getProjectsAuthority: () => api().getProjectsAuthority(),
        listAttachableSessions: () => api().listAttachableSessions(),
        getCurrentSession: () => api().getCurrentSession(),
        listSessionRecords: () => api().listSessionRecords(),
    };
    Object.defineProperty(host, 'listSessions', {
        enumerable: true,
        get() {
            const live = api();
            if (live && typeof live.listSessions === 'function') {
                return () => live.listSessions!();
            }
            return undefined;
        },
    });
    return host;
}
