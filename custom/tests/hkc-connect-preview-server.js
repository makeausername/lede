"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const port = Number(process.argv[2] || 18765);
const root = path.resolve(process.argv[3] || path.join("package", "lean", "luci-app-hkc-connect"));
let authenticated = false;
let running = false;
let selected = "line_hk";
let settings = { autoConnect: true, domesticProtection: true, autoUpdate: true, updateHour: 5, updateMinute: 0, gameUdp: true, gameUdpManaged: true };
const lines = [
	{ id: "line_hk", name: "香港 HKG-A", protocol: "VLESS" },
	{ id: "line_uk", name: "英国 UK-A", protocol: "VLESS" },
	{ id: "line_sg", name: "新加坡 SGP-A", protocol: "VLESS" }
];

function status() {
	const line = lines.find((item) => item.id === selected);
	return { hostname: "HKC", bound: true, running, connectionState: running ? "connected" : "disconnected", selectedNode: line ? { id: line.id, name: line.name, protocol: line.protocol } : null, account: { bound: true, email: "a***@example.com", name: "Demo", usage: { todayUsed: 1610612736, used: 125629235, total: 0, remaining: 0, isUnlimited: true, expireAt: "" } }, settings, lastUpdate: 0, lastUpdateStatus: "success", sync: { state: "success" } };
}
function json(res, code, data) { res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(data)); }

http.createServer((req, res) => {
	const url = new URL(req.url, `http://127.0.0.1:${port}`);
	if (url.pathname === "/cgi-bin/luci/hkc-connect") {
		const file = path.join(root, "luasrc", "view", "hkc_connect", "index.htm");
		res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Set-Cookie": "hkc_csrf=preview; Path=/cgi-bin/luci/hkc-connect; SameSite=Strict" }); return res.end(fs.readFileSync(file));
	}
	if (url.pathname === "/luci-static/resources/hkc-connect/app.css" || url.pathname === "/luci-static/resources/hkc-connect/app.js") {
		const name = path.basename(url.pathname); res.writeHead(200, { "Content-Type": name.endsWith("css") ? "text/css" : "text/javascript" }); return res.end(fs.readFileSync(path.join(root, "htdocs", "luci-static", "resources", "hkc-connect", name)));
	}
	if (!url.pathname.startsWith("/cgi-bin/luci/hkc-connect/api/")) { res.writeHead(404); return res.end(); }
	const action = url.pathname.slice("/cgi-bin/luci/hkc-connect/api/".length);
	if (action === "bootstrap") return json(res, 200, { ok: true, data: { authenticated, bound: authenticated, data: authenticated ? status() : undefined } });
	if (action === "login") { authenticated = true; res.setHeader("Set-Cookie", "hkc_session=preview; Path=/cgi-bin/luci/hkc-connect; HttpOnly; SameSite=Strict"); return json(res, 200, { ok: true, data: { account: status().account } }); }
	if (!authenticated) return json(res, 401, { ok: false, error: "authentication_required" });
	if (action === "status") return json(res, 200, { ok: true, data: status() });
	if (action === "lines") return json(res, 200, { ok: true, data: lines.map((item) => Object.assign({}, item, { selected: item.id === selected })) });
	if (action === "sync/status") return json(res, 200, { ok: true, data: { state: "success" } });
	let body = ""; req.on("data", (part) => { body += part; }); req.on("end", () => {
		const input = body ? JSON.parse(body) : {};
		if (action === "connect") { selected = input.nodeId; running = true; return json(res, 200, { ok: true, data: status() }); }
		if (action === "disconnect") { running = false; return json(res, 200, { ok: true, data: status() }); }
		if (action === "settings/update") { settings = Object.assign(settings, input); return json(res, 200, { ok: true, data: settings }); }
		if (action === "sync") return json(res, 200, { ok: true, data: { state: "queued" } });
		if (action === "logout") { authenticated = false; running = false; return json(res, 200, { ok: true }); }
		return json(res, 404, { ok: false, error: "not_found" });
	});
}).listen(port, "127.0.0.1", () => process.stdout.write(`HKC preview http://127.0.0.1:${port}/cgi-bin/luci/hkc-connect\n`));
