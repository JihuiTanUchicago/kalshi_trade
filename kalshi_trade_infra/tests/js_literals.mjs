// The string literals in a static script, with the line each starts on: '...', "..." and each template literal's
// own text (its ${...} parts are read as code, so a literal inside one is found too). Comments and regex literals
// are skipped. Enough of a tokenizer for the bundles' own code, not for every JavaScript program: a "/" reads as a
// regex where an expression starts (after an operator, a bracket, a comma or a keyword like return).
const REGEX_AFTER = /(?:^|[(,=:[!&|?{};+\-*%<>~^]|\b(?:return|typeof|case|in|of|delete|void|throw|new|else|do|yield|await))\s*$/;

export function literals(src) {
  const out = [];
  let i = 0, line = 1, last = '';  // last: the code just read, to tell a regex from a division
  const n = src.length;
  const step = () => { if (src[i] === '\n') line++; i++; };

  function quoted(q) {
    const start = line; let s = '';
    step();
    while (i < n && src[i] !== q) {
      if (src[i] === '\\') { s += src[i + 1] === 'n' ? '\n' : src[i + 1]; step(); step(); continue; }
      s += src[i]; step();
    }
    step();
    out.push({line: start, text: s});
  }

  function template() {
    const start = line; let s = '';
    step();
    while (i < n && src[i] !== '`') {
      if (src[i] === '\\') { s += src[i + 1]; step(); step(); continue; }
      if (src[i] === '$' && src[i + 1] === '{') { step(); step(); code('}'); step(); s += '\u0001'; continue; }
      s += src[i]; step();
    }
    step();
    out.push({line: start, text: s});
  }

  function regex() {
    step();
    let cls = false;
    while (i < n && (cls || src[i] !== '/')) {
      if (src[i] === '\\') { step(); step(); continue; }
      if (src[i] === '[') cls = true; else if (src[i] === ']') cls = false;
      step();
    }
    step();
    while (i < n && /[a-z]/.test(src[i])) step();
  }

  // Code up to the bracket that closes it (a template's "}"), or to the end.
  function code(close) {
    let depth = 0;
    last = '(';
    while (i < n) {
      const c = src[i];
      if (c === close && depth === 0) return;
      if (c === '{') depth++; else if (c === '}') depth--;
      if (c === '/' && src[i + 1] === '/') { while (i < n && src[i] !== '\n') step(); continue; }
      if (c === '/' && src[i + 1] === '*') { const end = src.indexOf('*/', i + 2); while (i < end + 2) step(); continue; }
      if (c === '\'' || c === '"') { quoted(c); last = 'x'; continue; }
      if (c === '`') { template(); last = 'x'; continue; }
      if (c === '/' && REGEX_AFTER.test(last)) { regex(); last = 'x'; continue; }
      last = (last + c).slice(-12);
      step();
    }
  }

  code(null);
  return out;
}

// A literal as a reader sees its words: markup and its attributes out, ${...} parts as "…".
export function prose(text) {
  return text
    .replace(/<[^<>]*>/g, ' ')            // whole tags, with their attributes (class, style, href)
    .replace(/<[a-zA-Z/][^<>]*$/, ' ')    // a tag left open for a ${...} attribute value
    .replace(/^[^<>\s]*>/, ' ')           // the tail of one closed after it ('">')
    .replace(/\u0001/g, '…');
}
