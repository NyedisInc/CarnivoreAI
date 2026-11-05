
Object.assign(API.prototype, {

    async getCatalogItems() {
        return await this.call('/catalog/items');
    },

    async getCatalogItem(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}`);
    },

    async getCatalogContents(itemId) {
        return await this.call(`/catalog/contents/${encodeURIComponent(itemId)}`);
    },

    async refreshCatalogIndex() {
        return await this.call('/catalog/index/refresh', { method: 'POST' });
    },

    async catalogOpened() {
        return await this.call('/catalog/refresh', { method: 'POST' });
    },

    async getCatalogInstalled() {
        return await this.call('/catalog/installed');
    },

    async previewCatalogInstall(request) {
        return await this.call('/catalog/install/preview', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    },

    async installCatalogItem(request) {
        return await this.call('/catalog/install', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    },

    async uninstallCatalogItem(installId) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'DELETE',
        });
    },

    async patchCatalogInstalled(installId, body) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'PATCH', body, expectedStatuses: [409],
        });
    },

    async updateCatalogInstalled(installId, body) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/update`,
            { method: 'POST', body, expectedStatuses: [409] },
        );
    },

    /* could not be read */
    async getCatalogItemRatings(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/ratings`);
    },

    async putCatalogItemRating(itemId, body) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'PUT', body, expectedStatuses: [400, 401, 404, 429],
        });
    },

    async deleteCatalogItemRating(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'DELETE', expectedStatuses: [400, 401, 404],
        });
    },

    /* could not be read */
    async getCatalogItemInstalls(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/installs`);
    },

    async getCatalogInstallCounts(ids) {
        return await this.call('/catalog/install-counts', { method: 'POST', body: { ids } });
    },
});
