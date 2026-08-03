"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const root = process.argv[2] || path.join("package", "lean", "luci-app-hkc-connect");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

const model = read("luasrc", "model", "hkc_connect.lua");
const controller = read("luasrc", "controller", "hkc_connect.lua");
const view = read("luasrc", "view", "hkc_connect", "index.htm");
const app = read("htdocs", "luci-static", "resources", "hkc-connect", "app.js");
const landing = read("root", "etc", "uci-defaults", "95-hkc-connect-landing");
const sync = read("root", "usr", "libexec", "hkc-connect-sync");
const repoRoot = path.resolve(root, "..", "..", "..");
const firstBootDefaults = fs.readFileSync(path.join(repoRoot, "custom", "hkc-defaults.sh.in"), "utf8");

assert.match(model, /storage\.replace\(cursor, url\)/, "must use the proven SSR Plus subscription owner seam");
assert.match(model, /cursor:set\(SSR_CONFIG, global_sid, "global_server", sid\)/, "must select lines through global_server");
assert.match(model, /pidof xray/, "the UI must verify the selected Xray process without extending the SSR init API");
assert.match(model, /busybox netstat -lnt/, "the UI must verify the selected proxy listener locally");
assert.doesNotMatch(model, /\/etc\/init\.d\/shadowsocksr running/, "the UI must not require a private SSR init command");
assert.match(model, /application\/x-www-form-urlencoded/, "panel login must support the deployed form parser");
assert.match(model, /}, nil, "form"\)/, "credentials must be submitted as a private form body");
assert.match(model, /SSR_BACKUP_FILE/, "must snapshot SSR configuration");
assert.match(model, /util\.shellquote\(SSR_BACKUP_FILE\) \.\. " \/etc\/config\/shadowsocksr"/, "must restore the snapshot after a failed start");
assert.match(model, /\/etc\/init\.d\/shadowsocksr failopen/, "disconnect must withdraw proxy rules through the existing fail-open path");
assert.match(model, /\/var\/run\/ssrplus\.fail-open/, "status must report the existing fail-open marker instead of inferring safety");
assert.doesNotMatch(model, /iptables\s+-|ip6tables\s+-|nft\s+/, "the UI layer must not own packet-filter rules");
assert.doesNotMatch(model, /gen_config\.lua|gen_config_file/, "the UI layer must not generate Xray configurations");

assert.match(controller, /SameSite=Strict/, "cookies must use SameSite=Strict");
assert.match(controller, /HttpOnly/, "the local management session must be HttpOnly");
assert.match(controller, /HTTP_X_HKC_CSRF/, "state-changing requests must have CSRF protection");
assert.match(controller, /REQUEST_METHOD.*POST/, "state-changing endpoints must reject non-POST requests");
assert.match(controller, /Content-Security-Policy/, "the standalone UI must set CSP");
assert.match(controller, /root\.leaf = false/, "the page route must allow its API children to dispatch");
assert.doesNotMatch(controller, /access_token|subscription_url|server_port|reality_publickey/, "controller responses must not expose credentials or node secrets");

assert.match(view, /\/cgi-bin\/luci\/admin/, "the original LuCI recovery path must stay reachable");
assert.match(view, /data-i18n="autoUpdate"/, "the production settings page must expose automatic updates");
assert.match(app, /navigator\.language/, "the UI must choose Chinese or English from the browser language");
assert.match(app, /textContent = line\.name/, "node names must be rendered as text, not HTML");
assert.doesNotMatch(app, /localStorage|sessionStorage/, "browser storage must not retain account or subscription data");
assert.doesNotMatch(app, /subscription(URL|Url|_url)|accessToken|server_port|publickey/i, "browser code must not request or handle sensitive node data");
assert.match(app, /waitForSync\(\)\.catch/, "login must observe the backend-started update");
assert.doesNotMatch(app, /loadAll\(\); syncLines\(\)/, "login must not launch a duplicate subscription update");

assert.match(landing, /\/cgi-bin\/luci\/hkc-connect/, "the root document must land on HKC Connect");
assert.match(landing, /\/cgi-bin\/luci\/admin/, "the landing installer must document the LuCI recovery path");
assert.match(sync, /ssrplusupdate\.sh/, "updates must delegate to the existing tested SSR Plus update wrapper");
assert.match(sync, /flock -n 9/, "updates must use an OS lock rather than trusting a stale UI status file");
assert.doesNotMatch(sync, /uci -q (delete|set) shadowsocksr\.@global/, "the update wrapper must not rewrite live proxy selection");
assert.doesNotMatch(firstBootDefaults, /global_xray_fragment|tlshello/, "the UI firmware must preserve the proven fragment=0 SSR baseline");
assert.ok(!fs.existsSync(path.join(repoRoot, "custom", "patches", "helloworld", "160-live-proven-runtime.patch")),
	"the rejected runtime override must not return");

console.log("HKC Connect static production checks passed");
