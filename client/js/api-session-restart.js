
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

    async restartSession(sessionUuid) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/restart`,
            { method: 'POST' }
        );
    },
});
