import { HostError } from "./frames.js";
import { Host } from "./host.js";
export class FakeHost {
    responses;
    calls = [];
    constructor(responses = {}) {
        this.responses = { ...responses };
    }
    send = async (method, params) => {
        this.calls.push({ method, params });
        const answer = this.responses[method];
        if (answer instanceof HostError) {
            throw answer;
        }
        if (typeof answer === "function") {
            const out = await answer(params);
            if (out instanceof HostError) {
                throw out;
            }
            return out;
        }
        return answer ?? {};
    };
}
export function attach(plugin, fakeHost) {
    plugin.host = new Host(fakeHost.send);
    return plugin;
}
export async function renderUi(plugin, surface, params = {}) {
    return await plugin.handle("ui.render", { surface, params });
}
