// Minimal DOM harness, NOT a rendering/browser test. No npm dependencies.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(__dirname + '/dashboard.html', 'utf8');
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.style={}; this.events={}; this.textContent=''; this.value=''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener(name, fn) { this.events[name]=fn; }
  focus() { this.focused=true; }
}
const elements = {};
for (const match of html.matchAll(/id="([^"]+)"/g)) elements[match[1]] = new Element('div');
elements.data.textContent = html.split('<script type="application/json" id="data">')[1].split('</script>')[0];
elements.site.value='all'; elements.mode.value='blocked';
const document = {getElementById: id=>elements[id],createElement: tag=>new Element(tag)};
const code = html.split('<script>')[1].split('</script>')[0];
vm.runInNewContext(code, {document, Intl, Date, Math});
const data = JSON.parse(elements.data.textContent);
const number = n=>n.toLocaleString('it-IT');
assert.strictEqual(elements.blocked.textContent, number(data.views.all.blocked.count));
assert.strictEqual(elements.monitor.textContent, number(data.views.all.would_block.count));
assert.strictEqual(elements.chart.children.length, 12);
elements.site.value='quiet'; elements.site.events.change();
assert.strictEqual(elements.blocked.textContent, '0');
assert.ok(elements.empty.textContent.includes('Nessun evento'));
assert.strictEqual(elements.freshness.textContent, 'Non disponibile');
elements.site.value='journal'; elements.site.events.change();
assert.strictEqual(elements.blocked.textContent, number(data.views.journal.blocked.count));
elements.mode.value='would_block'; elements.mode.events.change();
assert.strictEqual(elements.reasonmode.textContent, 'Monitor');
assert.strictEqual(elements.blocked.textContent, number(data.views.journal.blocked.count));
elements.reset.events.click();
assert.strictEqual(elements.site.value, 'all');
assert.strictEqual(elements.mode.value, 'blocked');
elements.sites.children[0].children[0].children[0].events.click();
assert.strictEqual(elements.site.value, 'journal');
assert.ok(elements.site.focused);
console.log('UI harness: initial view, filters, empty state, mode separation, reset and site buttons PASS');
