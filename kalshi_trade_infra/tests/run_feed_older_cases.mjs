// Shared cases, run against each bundle's research log (runFeed) on a live list (Tau and Meridian): a long session's
// page first gets only its newest lines, and "Show earlier steps" at the top of the log reads the page before the
// first line it has (`older(before, read)`), puts it above in order where the reader is, moves each standalone
// verdict onto its idea's card when that card arrives, and goes once nothing older is left. New lines still
// append at the foot, and a late verdict for an idea on an earlier page lands on its card.
import assert from './assert_text.mjs';
import {test} from 'node:test';

export function olderStepsCases({name, frontend, longFeed, runEvent}) {
  test(`${name}: "Show earlier steps" reads the page before the first line, puts it above in order, and live lines still append`, async () => {
    const f = frontend(), {stream, log} = longFeed(f);
    stream.push([runEvent(201, 'verdict', 'FAILED - Old idea: no edge', {title: 'Old idea', status: 'failed'}),
      runEvent(202, 'step', 'Step 202')]);
    const reads = [];
    const pages = {
      201: {events: [runEvent(199, 'hypothesis', 'Old idea', {thesis: 'Old'}), runEvent(200, 'step', 'Step 200')], more: true},
      199: {events: [runEvent(197, 'hypothesis', 'Pending idea', {thesis: 'Old'}), runEvent(198, 'step', 'Step 198')], more: false},
    };
    stream.older(201, async (before) => { reads.push(before); return pages[before]; });
    const button = () => log.children[0].querySelector('button');
    assert.equal(log.children[0].className, 'log-earlier');
    assert.equal(button().textContent, 'Show earlier steps');
    assert.equal(log.children.length, 3);  // the control, the verdict standing alone, Step 202

    await button().onclick({currentTarget: button()});
    assert.deepEqual(reads, [201]);
    // The earlier page sits above, in order; its idea took back the verdict that stood alone; more remain.
    assert.equal(log.children.length, 4);
    assert.equal(log.children[0].className, 'log-earlier'); assert.equal(button().textContent, 'Show earlier steps');
    assert.match(log.children[1].innerHTML, /Old idea/);
    assert.match(log.children[1].querySelector('[data-review]').innerHTML, /Verdict|failed|Void/i);
    assert.match(log.children[2].innerHTML, /Step 200/); assert.match(log.children[3].innerHTML, /Step 202/);
    assert.equal(log.children.filter((li) => /Old idea/.test(li.innerHTML)).length, 1);

    // A new line still goes at the foot.
    stream.push([runEvent(203, 'step', 'Step 203')]);
    assert.match(log.children.at(-1).innerHTML, /Step 203/);

    // The last page: the control goes. A later verdict for an idea on it lands on its card, not as a line.
    await button().onclick({currentTarget: button()});
    assert.deepEqual(reads, [201, 199]);
    assert.equal(log.querySelector('.log-earlier'), null);
    assert.match(log.children[0].innerHTML, /Pending idea/); assert.match(log.children[1].innerHTML, /Step 198/);
    const n = log.children.length;
    stream.push([runEvent(204, 'verdict', 'FAILED - Pending idea: no edge', {title: 'Pending idea', status: 'failed'})]);
    assert.equal(log.children.length, n);
    assert.match(log.children[0].querySelector('[data-review]').innerHTML, /Verdict|failed|Void/i);
  });

  test(`${name}: a failed read of earlier steps keeps the control to try again`, async () => {
    const f = frontend(), {stream, log} = longFeed(f);
    stream.push([runEvent(10, 'step', 'Step 10')]);
    let fail = true;
    stream.older(10, async () => { if (fail) throw new Error('offline'); return {events: [runEvent(9, 'step', 'Step 9')], more: false}; });
    const button = () => log.querySelector('.log-earlier button');
    await button().onclick({currentTarget: button()});
    assert.match(button().textContent, /Try again/); assert.equal(button().disabled, false);
    fail = false;
    await button().onclick({currentTarget: button()});
    assert.equal(log.querySelector('.log-earlier'), null);
    assert.match(log.children[0].innerHTML, /Step 9/); assert.match(log.children[1].innerHTML, /Step 10/);
  });

  test(`${name}: held rows show first, then the server's earlier steps, from one control at the top`, async () => {
    const f = frontend(), {stream, log} = longFeed(f);
    stream.push(Array.from({length: 120}, (_, i) => runEvent(i + 101, 'step', `Step ${i + 101}`)));
    stream.older(101, async () => ({events: [runEvent(100, 'step', 'Step 100')], more: false}));
    assert.equal(log.querySelectorAll('.log-earlier').length, 1);
    assert.match(log.children[0].innerHTML, /Show 60 earlier entries/);
    log.children[0].querySelector('button').onclick({currentTarget: log.children[0].querySelector('button')});
    assert.equal(log.children.length, 121); assert.equal(log.children[0].querySelector('button').textContent, 'Show earlier steps');
    assert.match(log.children[1].innerHTML, /Step 101/);
    const b = log.children[0].querySelector('button');
    await b.onclick({currentTarget: b});
    assert.equal(log.children.length, 121); assert.match(log.children[0].innerHTML, /Step 100/); assert.match(log.children[1].innerHTML, /Step 101/);
  });
}
