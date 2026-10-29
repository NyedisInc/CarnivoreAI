
export function singleFlightWithRerun(run: () => Promise<void>): () => Promise<void> {
    let current: Promise<void> | null = null;
    let trailing: Promise<void> | null = null;

    function start(): Promise<void> {
        const flight = run().finally(() => { if (current === flight) current = null; });
        current = flight;
        return flight;
    }

    return function refresh(): Promise<void> {
        if (!current) return start();
        if (!trailing) {
            const rerun = (): Promise<void> => { trailing = null; return start(); };
            trailing = current.then(rerun, rerun);
        }
        return trailing;
    };
}
