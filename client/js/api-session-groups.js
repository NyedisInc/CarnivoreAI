
console.log('[API Api Session Groups Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-session-groups.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {

    async listSessionGroups() {
        return await this.call('/session-groups');
    },

    /* list, so the */
    async createSessionGroup(name) {
        return await this.call('/session-groups', { method: 'POST', body: { name } });
    },

    async renameSessionGroup(groupUuid, name) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}`, {
            method: 'PATCH', body: { name },
        });
    },

    async deleteSessionGroup(groupUuid) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}`, {
            method: 'DELETE',
        });
    },

    async assignSessionGroup(name, groupUuid) {
        const L = window.SessionSidebarLayouts;
        const isLayout = !!(L && typeof L.isLayoutName === 'function' && L.isLayoutName(name));
        const body = isLayout
            ? { layout_uuid: L.idOf(name), group_uuid: groupUuid }
            : { tmux_name: name, group_uuid: groupUuid };
        return await this.call('/session-groups/assign', { method: 'POST', body });
    },

    async reorderSessionGroups(groupUuids) {
        return await this.call('/session-groups/order', {
            method: 'POST', body: { group_uuids: groupUuids },
        });
    },

    async reorderSessionGroupMembers(groupUuid, sessionUuids) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/order`, {
            method: 'POST', body: { session_uuids: sessionUuids },
        });
    },

    async setSessionGroupStyle(groupUuid, style) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/style`, {
            method: 'PUT',
            body: {
                colour: style.colour,
                gradient: style.gradient || null,
                animation: style.animation || 'none',
            },
        });
    },

    async setSessionGroupIcon(groupUuid, icon) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/icon`, {
            method: 'PUT', body: { icon: icon || null },
        });
    },

    async setSessionGroupRule(groupUuid, rule) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/rule`, {
            method: 'PUT', body: { flags: rule.flags || [], prefix: rule.prefix || '', suffix: rule.suffix || '' },
        });
    },
});
