(function (global) {
    function shouldReplace(held, incoming) {
        const heldVersion = held ? held.version : undefined;
        const incomingVersion = incoming ? incoming.version : undefined;
        if (heldVersion === undefined || heldVersion === null
            || incomingVersion === undefined || incomingVersion === null) {
            return true;
        }
        return incomingVersion > heldVersion;
    }

    const api = { shouldReplace: shouldReplace };

    global.ToastVersionArbitration = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[ToastVersionArbitration Module] Exported as window.ToastVersionArbitration');
