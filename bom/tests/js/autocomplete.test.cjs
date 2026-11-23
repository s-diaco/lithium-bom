const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../static/bom/js/jquery.autocomplete-bom.js"), "utf8"
);

function harness(attrs = {}) {
  const requests = [];
  const timers = new Map();
  const ready = [];
  let nextTimer = 0;
  let submits = 0;
  class Element {
    constructor() {
      this.events = {};
      this.children = [];
      this.value = "";
      this.visible = false;
      this.form = { submit() { submits += 1; } };
    }
    getAttribute(name) { return attrs[name] || null; }
  }
  const input = new Element();
  const parent = new Element();
  let list;
  class Collection {
    constructor(elements) { this.elements = elements; }
    each(fn) { this.elements.forEach((el) => fn.call(el)); return this; }
    css() { return this; }
    parent() { return new Collection([parent]); }
    after(collection) { list = collection.elements[0]; return this; }
    hide() { return this.each(function () { this.visible = false; }); }
    show() { return this.each(function () { this.visible = true; }); }
    empty() { return this.each(function () { this.children = []; }); }
    append(collection) { this.elements[0].children.push(collection.elements[0]); return this; }
    text(value) { this.elements[0].text = value; return this; }
    val(value) {
      if (arguments.length === 0) return this.elements[0].value;
      return this.each(function () { this.value = value; });
    }
    on(name, fn) { return this.each(function () { this.events[name] = fn; }); }
  }
  function $(value) {
    if (typeof value === "function") { ready.push(value); return; }
    if (value === "input[data-part-autocomplete]") {
      return new Collection(attrs["data-part-autocomplete"] ? [input] : []);
    }
    if (typeof value === "string") return new Collection([new Element()]);
    return new Collection([value]);
  }
  $.fn = Collection.prototype;
  $.getJSON = (url, params) => {
    const request = { url, params };
    requests.push(request);
    const promise = {
      done(fn) { request.done = fn; return promise; },
      fail(fn) { request.fail = fn; return promise; },
    };
    return promise;
  };
  vm.runInNewContext(source, {
    jQuery: $,
    setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  return {
    input, requests,
    get list() { return list; },
    get submits() { return submits; },
    init(options) { $(input).autocomplete(options); },
    ready() { ready.forEach((fn) => fn()); },
    type(value) { input.value = value; input.events.input(); },
    flush() { const pending = [...timers.values()]; timers.clear(); pending.forEach((fn) => fn()); },
    choose() { list.children[0].events.mousedown({ preventDefault() {} }); },
  };
}

test("remote labels render as text and selection returns only the part number", () => {
  const h = harness();
  let selected;
  h.init({ source: "/suggest/", limit: 8, onAutocomplete(value) { selected = value; } });
  h.type("100");
  assert.equal(h.requests[0].params.limit, 8);
  h.requests[0].done({ results: [{ value: "100-0001", label: "100-0001 ┆ <script>description</script>" }] });
  assert.equal(h.list.children[0].text, "100-0001 ┆ <script>description</script>");
  h.choose();
  assert.equal(selected, "100-0001");
  assert.equal(h.list.visible, false);
});

test("shared widget initialization fills PN and honors submit and result limits", () => {
  for (const submit of ["true", "false"]) {
    const h = harness({
      "data-part-autocomplete": "/suggest/?exclude_part_id=4",
      "data-autocomplete-limit": "8",
      "data-autocomplete-submit": submit,
    });
    h.ready();
    h.type("100");
    assert.equal(h.requests.length, 0);
    h.flush();
    assert.equal(h.requests[0].url, "/suggest/?exclude_part_id=4");
    h.requests[0].done({ results: [{ value: "100-0001", label: "100-0001 ┆ Description" }] });
    h.choose();
    assert.equal(h.input.value, "100-0001");
    assert.equal(h.submits, submit === "true" ? 1 : 0);
  }
});

test("local string sources retain their label callback behavior", () => {
  const h = harness();
  let selected;
  h.init({ data: { "PN ┆ Description": null }, onAutocomplete(value) { selected = value; } });
  h.type("description");
  assert.equal(h.list.children[0].text, "PN ┆ Description");
  h.choose();
  assert.equal(selected, "PN ┆ Description");
});

test("old responses are ignored immediately while a new query is debouncing", () => {
  const h = harness();
  h.init({ source: "/suggest/", debounce: 200, minLength: 1 });
  h.type("old");
  h.flush();
  h.type("new");
  h.requests[0].done({ results: ["stale"] });
  assert.equal(h.list.visible, false);
  h.flush();
  h.requests[1].done({ results: ["fresh"] });
  assert.equal(h.list.children[0].text, "fresh");
  h.type("");
  h.requests[1].done({ results: ["stale again"] });
  assert.equal(h.list.visible, false);
});

test("blur cancels pending debounce and prevents late responses reopening suggestions", () => {
  const h = harness();
  h.init({ source: "/suggest/", debounce: 200 });
  h.type("old");
  h.flush();
  h.type("new");
  h.input.events.blur();
  h.flush();
  assert.equal(h.requests.length, 1);
  h.requests[0].done({ results: ["stale"] });
  assert.equal(h.list.visible, false);
});
