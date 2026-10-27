// node:assert/strict, comparing text as a reader sees it. The money formatters put a word joiner (U+2060,
// invisible and zero width) between a sign and "$" so a line never ends on "−" with "$13.56" on the next
// (usd() in app.js and app.meridian.js). Assertions written as "−\$13\.56" or '+$2.00' keep checking the same
// visible text: each comparison takes the joiner out of both sides first, and nothing else. A doesNotMatch
// reads the visible text too, so "−\$" can't slip past it by having a joiner in the middle.
// tests/test_money_word_joiner.mjs checks the joiner itself, with plain node:assert, where it must be (on the
// screen) and where it must never be (attributes, the tab title, the clipboard, downloads).
import strict from 'node:assert/strict';

const WJ = /⁠/g;
// The value with the joiner taken out of every string in it; the value itself when it has none, so an
// equal() on objects still compares references.
export const visible = (v) => {
  if (typeof v === 'string') return v.replace(WJ, '');
  if (Array.isArray(v)) {
    const out = v.map(visible);
    return out.some((x, i) => x !== v[i]) ? out : v;
  }
  if (v && typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype) {
    const out = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, visible(x)]));
    return Object.keys(v).some((k) => out[k] !== v[k]) ? out : v;
  }
  return v;
};

const assert = (value, message) => strict(value, message);
Object.assign(assert, strict, {
  match: (actual, re, message) => strict.match(visible(actual), re, message),
  doesNotMatch: (actual, re, message) => strict.doesNotMatch(visible(actual), re, message),
  equal: (actual, expected, message) => strict.equal(visible(actual), visible(expected), message),
  notEqual: (actual, expected, message) => strict.notEqual(visible(actual), visible(expected), message),
  deepEqual: (actual, expected, message) => strict.deepEqual(visible(actual), visible(expected), message),
  strictEqual: (actual, expected, message) => strict.strictEqual(visible(actual), visible(expected), message),
  deepStrictEqual: (actual, expected, message) => strict.deepStrictEqual(visible(actual), visible(expected), message),
});
export default assert;
