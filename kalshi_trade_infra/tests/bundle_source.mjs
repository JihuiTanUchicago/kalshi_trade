// A theme's code as the browser runs it: the shared core both themes take their pure helpers from
// (core.js, run before the bundle), the bundle (app.js, app.meridian.js), then each page file it fetches
// on first use (app-<name>.js, app.meridian-<name>.js, app/web/page_modules.py), in one script.
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

// The core's source: what a check that runs a bundle on its own runs ahead of it, as the page does.
export const coreSource = () => read('core.js');

// A script with its comments, strings, template text and regex literals blanked (every line kept, a template's
// ${...} kept as code): what is left is the code, so a check for a name finds only where the code uses it,
// never a word in a definition ("history") or a comment. A `/` starts a regex unless it follows a name, a
// number or a closing bracket, as in this codebase's style.
const REGEX_AFTER = new Set(['return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw', 'case', 'do', 'else', 'yield', 'await']);
export function codeOnly(src) {
  const out = src.split(''), blank = (i) => { if (out[i] !== '\n') out[i] = ' '; };
  const braces = [];  // per open template ${...}: how many { deep its code is
  let i = 0, last = '';  // the last significant token, for the regex-or-divide call
  const text = (end, from) => { for (; i < src.length && !end(); i++) { if (src[i] === '\\') { blank(i); i++; } blank(i); } return from; };
  const template = () => {  // at a template's text: up to its end (`) or its next ${
    for (; i < src.length; i++) {
      if (src[i] === '\\') { blank(i); blank(i + 1); i++; continue; }
      if (src[i] === '`') { i++; last = '`'; return; }
      if (src[i] === '$' && src[i + 1] === '{') { blank(i); braces.push(0); i += 2; last = '{'; return; }
      blank(i);
    }
  };
  while (i < src.length) {
    const c = src[i], d = src[i + 1];
    if (c === '/' && d === '/') { while (i < src.length && src[i] !== '\n') blank(i++); continue; }
    if (c === '/' && d === '*') { const end = src.indexOf('*/', i + 2); const stop = end < 0 ? src.length : end + 2; while (i < stop) blank(i++); continue; }
    if (c === '"' || c === "'") { i++; text(() => src[i] === c || src[i] === '\n'); i++; last = 'str'; continue; }
    if (c === '`') { i++; template(); continue; }
    if (c === '/' && !/^(?:[\w$]+|[)\]}]|str|`)$/.test(last) || c === '/' && REGEX_AFTER.has(last)) {
      i++;
      let cls = false;
      for (; i < src.length && src[i] !== '\n'; i++) {
        if (src[i] === '\\') { blank(i); blank(++i); continue; }
        if (src[i] === '[') cls = true; else if (src[i] === ']') cls = false; else if (src[i] === '/' && !cls) break;
        blank(i);
      }
      i++; while (/[a-z]/.test(src[i] || '')) blank(i++);
      last = 'str'; continue;
    }
    if (braces.length && c === '{') braces[braces.length - 1]++;
    if (braces.length && c === '}') { if (braces[braces.length - 1]-- === 0) { braces.pop(); i++; template(); continue; } }
    const word = /^[\w$]+/.exec(src.slice(i, i + 64));
    if (word) { last = word[0]; i += word[0].length; continue; }
    if (!/\s/.test(c)) last = c;
    i++;
  }
  return out.join('');
}

// The core, the bundle and its page files. With `expose`, each page file also adds the listed bindings it has to
// globalThis[target] as it runs, as a harness's boot replacement does for the bundle's own. The bundle's
// win: a view a page file holds stays the router's stand-in for it (pageView), as the routes hold it.
export function bundleSource(bundle, {expose = [], target = 'frontend'} = {}) {
  const tail = /\n( {2}return \{[\w, ]+\};\n\}\);\n)$/;
  const pages = pageFiles(bundle).map((f) => {
    const src = read(f);
    if (!tail.test(src)) throw new Error(f + ': a page file ends with the views it returns');
    return expose.length ? src.replace(tail, `\n  globalThis.${target} = Object.assign(${exposing(expose)}, globalThis.${target});\n$1`) : src;
  });
  return [coreSource(), read(bundle), ...pages].join('\n');
}
