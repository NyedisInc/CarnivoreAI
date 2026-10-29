
console.log('[API Session Lifecycle Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-session-lifecycle.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {
    async destroyExternalSession(sessionName) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/external/${encodeURIComponent(sessionName)}${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    },

    /* restart the agent */
    async restartPreview(sessionName) {
        /* could not be read */
        const qs = encodeURIComponent(sessionName);
        return await this.call(`/sessions/restart/preview?session_name=${qs}`);
    },

    async recreatePreview(sessionUuid) {
        const qs = encodeURIComponent(sessionUuid);
        return await this.call(`/sessions/recreate/preview?session_uuid=${qs}`);
    },

    async restartAccounts(sessionUuid) {
        return await this.call(`/sessions/${encodeURIComponent(sessionUuid)}/restart/accounts`);
    },

    async recreateSession(sessionUuid, agentType, account) {
        const body = { session_uuid: sessionUuid, agent_type: agentType };
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        return await this.call('/sessions/recreate', { method: 'POST', body });
    },

    async respawnSession(sessionName, agentType, confirmRestartLive, account) {
        const body = { session_name: sessionName };
        if (agentType) body.agent_type = agentType;
        if (confirmRestartLive === true) body.confirm_restart_live = true;
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        return await this.call('/sessions/respawn', {
            method: 'POST',
            body,
        });
    },

    async renameSession(sessionId, newName) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/name`,
            {
                method: 'PATCH',
                body: { new_name: newName },
            }
        );
    },

    async setSessionUnread(tmuxName, unread) {
        return await this.call(
            `/sessions/${encodeURIComponent(tmuxName)}/unread`,
            {
                method: 'PATCH',
                body: { unread: !!unread },
            }
        );
    },

    /* the current session */
    async detachSession(sessionId = null) {
        const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        return await this.call(`/sessions/detach${q}`, {
            method: 'POST'
        });
    },

    async listAttachableSessions() {
        return await this._listingRead('attachable', '/sessions/attachable');
    },

    async listRecentSessions(includeArchived = false) {
        return await this.call(
            includeArchived
                ? '/sessions/recent?include_archived=true'
                : '/sessions/recent'
        );
    },

    async listSessionRecords() {
        return await this._listingRead('records', '/sessions/records');
    },

    async listSessionCompanions() {
        return await this._listingRead('companions', '/sessions/companions');
    },

    async listArchivedSessionRecords() {
        return await this.call('/sessions/records?archived_only=true');
    },

    /* could not be reached */
    async forkSession(sessionName) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionName)}/fork`,
            { method: 'POST' }
        );
    },

    async restartSession(sessionUuid) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/restart`,
            { method: 'POST' }
        );
    },

    async sleepSession(sessionUuid) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/sleep`,
            { method: 'POST' }
        );
    },

    async wakeSession(sessionUuid, agentType, account, startFresh) {
        const init = { method: 'POST' };
        const body = {};
        if (agentType) body.agent_type = agentType;
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        if (startFresh === true) body.start_fresh = true;
        if (Object.keys(body).length) init.body = body;
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/wake`,
            init
        );
    },

    async killAsleepSession(sessionUuid) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/asleep${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    },

    async deleteSessionRecord(sessionUuid) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/records/${encodeURIComponent(sessionUuid)}${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    },

    /* the current session */
    async adoptSession(sessionName, confirmDetach = false, controller = null) {
        const vote = window.TerminalSizeVote;
        const grid = vote && typeof vote.adoptGrid === 'function' ? vote.adoptGrid(controller, document) : {};
        return await this.call('/sessions/adopt', {
            method: 'POST',
            body: {
                session_name: sessionName,
                confirm_detach: confirmDetach,
                ...(grid.cols && grid.rows
                    ? { cols: grid.cols, rows: grid.rows }
                    : {}),
            },
        });
    },
});
