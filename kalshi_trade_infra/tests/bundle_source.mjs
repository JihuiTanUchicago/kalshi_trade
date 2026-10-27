// A theme's code as the browser runs it: the bundle (app.js, app.meridian.js), then each page file it
// fetches on first use (app-<name>.js, app.meridian-<name>.js, app/web/page_modules.py), in one script.
// Every page's code is in, registered with the bundle as it would be once fetched, so a harness that
// renders any page, or a check that reads the source, covers the page files too.
import {readdirSync, readFileSync} from 'node:fs';

const DIR = new URL('../app/static/', import.meta.url);
const read = (name) => readFileSync(new URL(name, DIR), 'utf8');

// The bundle's page files, by name: Tau's are app-<name>.js, Meridian's app.meridian-<name>.js.
export function pageFiles(bundle) {
  const prefix = bundle === 'app.js' ? 'app-' : bundle.replace(/\.js$/, '-');
  return readdirSync(DIR).filter((f) => f.startsWith(prefix) && /^[a-z.]+-[a-z]+\.js$/.test(f)).sort();
}

// An object of the named bindings that are in scope where it is evaluated: a harness lists what it
// reads without knowing whether each lives in the bundle or in a page file.
export const exposing = (names) => '{' + names.map((n) => `...(typeof ${n} === 'undefined' ? {} : {${n}})`).join(', ') + '}';

// The bundle and its page files. With `expose`, each page file also adds the listed bindings it has to
// globalThis[target] as it runs, as a harness's boot replacement does for the bundle's own. The bundle's
// win: a view a page file holds stays the router's stand-in for it (pageView), as the routes hold it.
export function bundleSource(bundle, {expose = [], target = 'frontend'} = {}) {
  const tail = /\n( {2}return \{[\w, ]+\};\n\}\);\n)$/;
  const pages = pageFiles(bundle).map((f) => {
    const src = read(f);
    if (!tail.test(src)) throw new Error(f + ': a page file ends with the views it returns');
    return expose.length ? src.replace(tail, `\n  globalThis.${target} = Object.assign(${exposing(expose)}, globalThis.${target});\n$1`) : src;
  });
  return [read(bundle), ...pages].join('\n');
}
