// Lets the macro's `import xapi from 'xapi'` load under Node during tests.
import { register } from 'node:module';

globalThis.__CALL_SWITCHER_TEST__ = true;

register(
  'data:text/javascript,' +
    encodeURIComponent(`
      export async function resolve(specifier, context, next) {
        if (specifier === 'xapi') {
          return { url: 'data:text/javascript,export default {}', shortCircuit: true };
        }
        return next(specifier, context);
      }
    `),
);
