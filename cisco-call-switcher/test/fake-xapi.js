// A small stand-in for the RoomOS `xapi` object, used only by the tests.
// It records every command the macro sends and lets tests fire status
// changes and events the way a real device would.

export function createFakeXapi() {
  const commands = [];
  const listeners = new Map(); // path -> [callback]
  const statusValues = new Map(); // path -> value
  const commandHandlers = new Map(); // path -> fn(args, body)

  function node(path) {
    const fn = (args, body) => {
      commands.push({ path, args: args ?? {}, body });
      const handler = commandHandlers.get(path);
      try {
        return Promise.resolve(handler ? handler(args ?? {}, body) : {});
      } catch (err) {
        return Promise.reject(err);
      }
    };
    return new Proxy(fn, {
      get(_target, prop) {
        if (prop === 'on') {
          return (cb) => {
            if (!listeners.has(path)) listeners.set(path, []);
            listeners.get(path).push(cb);
            return () => {
              const list = listeners.get(path) || [];
              listeners.set(path, list.filter((l) => l !== cb));
            };
          };
        }
        if (prop === 'get') {
          return () => Promise.resolve(statusValues.get(path) ?? []);
        }
        if (typeof prop === 'symbol') return undefined;
        return node(path ? `${path}.${prop}` : prop);
      },
    });
  }

  const xapi = node('');

  return {
    xapi,
    commands,
    /** Commands sent to a given path, e.g. 'Command.Call.Hold'. */
    sent(path) {
      return commands.filter((c) => c.path === path);
    },
    clear() {
      commands.length = 0;
    },
    setStatus(path, value) {
      statusValues.set(path, value);
    },
    onCommand(path, handler) {
      commandHandlers.set(path, handler);
    },
    async emit(path, payload) {
      for (const cb of listeners.get(path) || []) cb(payload);
      await flush();
    },
  };
}

/** Let pending promise callbacks run. */
export async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r));
}
