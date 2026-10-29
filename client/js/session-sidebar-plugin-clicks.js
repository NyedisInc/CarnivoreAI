
console.log('[SessionSidebarPluginClicks Module] Loading...');

(function () {
    async function onShareMarkClick(ctrl, el) {
        const plugins = window.CloudeWeb && window.CloudeWeb.rowMenu;
        if (!plugins || typeof plugins.runCplug !== 'function') {
            console.error('SessionSidebar: the row menu bridge (CloudeWeb.rowMenu) is not loaded,'
                + ' the share dialog cannot open');
            return;
        }
        await plugins.runCplug('share', {
            name: el.getAttribute('data-share-session') || '',
            sessionId: el.getAttribute('data-share-session-id') || null,
        });
        ctrl._lastSig = null;
        await ctrl._fetchAndRender();
    }

    window.SessionSidebarPluginClicks = { onShareMarkClick };
    console.log(
        '[SessionSidebarPluginClicks Module] Exported as window.SessionSidebarPluginClicks');
})();
