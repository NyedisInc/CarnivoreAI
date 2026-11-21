
function extendPrototype(Target, methods, source) {
    const clashes = [];
    for (const name of Object.keys(methods)) {
        if (Object.prototype.hasOwnProperty.call(Target.prototype, name)) clashes.push(name);
        else Target.prototype[name] = methods[name];
    }
    if (!clashes.length) return;
    const message = `${source} redefines ${Target.name}.prototype method(s): ${clashes.join(', ')}`;
    if (globalThis.__EXTEND_PROTOTYPE_STRICT__ === true) throw new Error(message);
    console.error(message);
    if (typeof reportError === 'function') reportError(new Error(message));
}
