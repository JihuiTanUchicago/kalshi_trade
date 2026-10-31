// Shared cases, run against each bundle's offline harness (Tau and Meridian): Settings and Billing as a paying
// customer (walk 2026-10-31). Flipping the email switch left focus at the top of the page; a save that failed said
// only "Something went wrong on our side." without whether the email setting or auto-reload had changed; and Try
// again on a Billing page that didn't load left focus at the top of the document once the page drew.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
// Each harness records focus its own way: Tau's marks the element, Meridian's moves activeElement.
const hasFocus = (f, el) => !!el && (el.focused === true || f.document.activeElement === el);

export function settingsBillingCases({name, frontend, billingPage, cardedBilling}) {
  test(`${name}: the email switch keeps keyboard focus through a save, and a failed save says the setting stands`, async () => {
    let fail = false, f;
    f = frontend({fetchImpl: (path, options) => {
      assert.equal(path, '/api/email-preferences');
      f.document.activeElement = f.document.body;  // the browser blurs the switch the save disables
      if (fail) return response({error: 'Something went wrong on our side.'}, 500);
      return response({ok: true, email_opt_out: JSON.parse(options.body).email_opt_out});
    }});
    f.S.me.user = {...f.S.me.user, email_opt_out: false};
    await f.viewSettings();
    const sw = f.root.querySelector('#email-optional');
    f.document.activeElement = sw; sw.focused = false;
    sw.checked = false; await sw.onchange(); await settle();
    assert.equal(f.S.me.user.email_opt_out, true);
    assert.ok(hasFocus(f, sw), 'focus is back on the switch');
    fail = true;
    f.document.activeElement = sw; sw.focused = false;
    sw.checked = true; await sw.onchange(); await settle();
    assert.equal(sw.checked, false);
    assert.equal(plain(f.root.querySelector('#email-flash').innerHTML), 'Something went wrong on our side. Optional email is still off.');
    assert.ok(hasFocus(f, sw), 'focus is back on the switch after a failed save');
    // A press that came from elsewhere (focus not on the switch) doesn't pull focus to it.
    fail = false;
    const other = f.root.querySelector('[data-theme]');
    f.document.activeElement = other; sw.focused = false;
    sw.checked = true; await sw.onchange(); await settle();
    assert.equal(sw.focused === true, false);
  });

  test(`${name}: a failed auto-reload save says what still stands, on or off and at which amounts`, async () => {
    const posts = [];
    let fail = false;
    const f = billingPage(cardedBilling({auto_reload: true, autoreload_amount: 25, autoreload_threshold: 8}), posts, {
      '/api/billing/auto-reload': (options) => { posts.push(JSON.parse(options.body)); return fail ? response({error: 'Something went wrong on our side.'}, 500) : response({ok: true}); }});
    await f.viewBilling(); await settle();
    const box = f.root.querySelector('#autoreload');
    fail = true;
    box.checked = false; await box.onchange(); await settle();
    assert.equal(box.checked, true);
    assert.equal(plain(f.root.querySelector('#autorel-flash').innerHTML), 'Something went wrong on our side. Auto-reload is still on: it reloads $25.00 at $8.00.');
    fail = false;
    box.checked = false; await box.onchange(); await settle();
    fail = true;
    box.checked = true; await box.onchange(); await settle();
    assert.equal(box.checked, false);
    assert.equal(plain(f.root.querySelector('#autorel-flash').innerHTML), 'Something went wrong on our side. Auto-reload is still off.');
    assert.deepEqual(posts.map((p) => p.on), [false, false, true]);
    f.clearTimers();
  });

  test(`${name}: Try again on a Billing page that didn't load puts focus on its heading once it draws`, async () => {
    let fail = true;
    // The page's first read fails; the second, after Try again, answers.
    const routes = new Proxy({}, {get: (_, path) => (fail && /^\/api\/billing(\?|$)/.test(String(path))
      ? () => response({error: 'Something went wrong on our side.'}, 500) : undefined)});
    const f = billingPage(cardedBilling(), [], routes);
    f.location.pathname = '/billing';
    await f.render(); await settle();
    assert.match(f.root.innerHTML, /This page didn’t load/);
    const again = f.root.querySelector('[data-retry]');
    f.document.activeElement = again;
    fail = false;
    await again.onclick(); await settle();
    const h1 = f.root.querySelector('main h1') || f.root.querySelector('h1');
    assert.ok(h1 && /Billing/.test(h1.textContent), 'Billing drew');
    assert.ok(hasFocus(f, h1), 'focus is on the page heading');
    f.clearTimers();
  });

  test(`${name}: removing a card says so and puts focus on the Payment method heading, not the top of the page`, async () => {
    const removed = [];
    const f = billingPage(cardedBilling(), [], {'/api/billing/remove-card': (options) => { removed.push(JSON.parse(options.body)); return response({ok: true}); }});
    await f.viewBilling(); await settle();
    const remove = f.root.querySelector('[data-remove="pm_2"]');
    f.document.activeElement = remove;
    remove.onclick(); f.elapse(500);
    await remove.onclick(); await settle();
    assert.deepEqual(removed, [{payment_method_id: 'pm_2'}]);
    assert.equal(plain(f.root.querySelector('#flash').innerHTML), 'Card removed.');
    const head = f.root.querySelector('.panel h2');
    assert.equal(head.textContent, 'Payment method');
    assert.ok(hasFocus(f, head), 'focus is on the Payment method heading');
    f.clearTimers();
  });
}
