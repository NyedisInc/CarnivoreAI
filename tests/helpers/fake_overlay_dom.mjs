
export function makeNode() {
    const handlers = {};
    return {
        handlers, disabled: false, hidden: false, checked: false, textContent: '', value: '', dataset: {}, style: {},
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
        removeEventListener(type, fn) { handlers[type] = (handlers[type] || []).filter((f) => f !== fn); },
        setAttribute() {}, removeAttribute() {}, focus() {}, click() { (handlers.click || []).forEach((f) => f({ target: this })); },
        querySelector() { return makeNode(); }, querySelectorAll: () => [], appendChild() {}, remove() {},
        fire(type, ev = {}) { (handlers[type] || []).forEach((f) => f({ target: this, ...ev })); },
    };
}

export function makeDom(absent = []) {
    const overlays = [];
    const body = { children: [], appendChild(el) { this.children.push(el); el.parentNode = body; }, removeChild(el) { this.children = this.children.filter((c) => c !== el); el.parentNode = null; } };
    const document = {
        body,
        createElement() {
            const nodes = {};
            const el = Object.assign(makeNode(), {
                className: '', innerHTML: '', parentNode: null,
                querySelector(sel) { return absent.includes(sel) ? null : (nodes[sel] ||= makeNode()); },
                nodes,
            });
            overlays.push(el);
            return el;
        },
        addEventListener() {}, removeEventListener() {},
    };
    return { document, overlays, body };
}
