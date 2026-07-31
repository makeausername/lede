#!/usr/bin/env node
'use strict';

const fs = require('fs');
const vm = require('vm');

const template = process.argv[2];
if (!template) {
  throw new Error('usage: test-classic-subscribe-commit.js <template>');
}

const source = fs.readFileSync(template, 'utf8')
  .replace(/^.*?\/\/<!\[CDATA\[/s, '')
  .replace(/\/\/\]\]>.*$/s, '');

class FakeInput {
  constructor(form) {
    this.form = form || null;
    this.parentNode = null;
    this.type = '';
    this.name = '';
    this.value = '';
    this.id = '';
    this.attributes = {};
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  closest() {
    return this;
  }
}

class FakeForm {
  constructor() {
    this.children = [];
  }

  appendChild(node) {
    node.form = this;
    node.parentNode = this;
    this.children.push(node);
  }

  removeChild(node) {
    this.children = this.children.filter((child) => child !== node);
    node.parentNode = null;
  }

  querySelector(selector) {
    if (selector === 'input[data-ssr-subscribe-presence="1"]') {
      return this.children.find((node) =>
        node.attributes['data-ssr-subscribe-presence'] === '1') || null;
    }
    return null;
  }

  querySelectorAll(selector) {
    if (selector === 'input[data-ssr-subscribe-pending="1"]') {
      return this.children.filter((node) =>
        node.attributes['data-ssr-subscribe-pending'] === '1');
    }
    return [];
  }
}

const listeners = {};
const form = new FakeForm();
let pending = new FakeInput(form);
pending.id = 'widget.cbid.shadowsocksr.global._classic_subscribe_urls';
pending.value = 'https://subscription.invalid/token';

const document = {
  querySelector() {
    return pending;
  },
  createElement() {
    return new FakeInput();
  },
  addEventListener(type, callback) {
    listeners[type] = callback;
  }
};

vm.runInNewContext(source, { document });
if (typeof listeners.submit !== 'function' ||
    typeof listeners.click !== 'function') {
  throw new Error('submit and click guards were not registered');
}

listeners.submit({ target: form });
let submitted = form.children.filter((node) =>
  node.name === 'cbid.shadowsocksr.global._classic_subscribe_urls');
if (submitted.length !== 1 ||
    submitted[0].value !== 'https://subscription.invalid/token') {
  throw new Error('pending subscription was not submitted directly');
}

let markers = form.children.filter((node) =>
  node.name === 'cbid.shadowsocksr.global._classic_subscribe_urls.__present');
if (markers.length !== 1 || markers[0].value !== '1') {
  throw new Error('explicit-presence marker was not submitted');
}

listeners.submit({ target: form });
submitted = form.children.filter((node) =>
  node.name === 'cbid.shadowsocksr.global._classic_subscribe_urls');
if (submitted.length !== 1) {
  throw new Error('repeated preparation duplicated the pending value');
}

pending.value = '   ';
listeners.submit({ target: form });
submitted = form.children.filter((node) =>
  node.name === 'cbid.shadowsocksr.global._classic_subscribe_urls');
markers = form.children.filter((node) =>
  node.name === 'cbid.shadowsocksr.global._classic_subscribe_urls.__present');
if (submitted.length !== 0 || markers.length !== 1) {
  throw new Error('empty list submission did not preserve delete intent');
}

pending = null;
listeners.submit({ target: form });
