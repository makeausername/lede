(function () {
	"use strict";

	const API = "/cgi-bin/luci/hkc-connect/api/";
	const $ = (id) => document.getElementById(id);
	const locale = /^zh\b/i.test(navigator.language || "") ? "zh" : "en";
	const copy = {
		zh: {
			secureRouter: "安全路由器", heroTitle: "让路由连接<br>像 App 一样简单", heroText: "使用你的面板账号登录，选择线路并连接。复杂的网络配置仍由路由器在后台安全完成。",
			deviceConsole: "设备控制台", loginDevice: "登录设备", loginHint: "使用 EzIPLC 面板账号管理这台 HKC 路由器。", email: "邮箱", password: "密码", totp: "动态验证码（如已启用）", login: "登录并绑定", privacy: "账号令牌仅以受限权限保存在路由器本机；页面不会读取订阅地址或节点密钥。",
			routerOnline: "路由器在线", connectionCenter: "连接中心", home: "首页", refresh: "刷新", disconnected: "未连接", connected: "已连接", protected: "已进入国内网络保护", ready: "准备就绪", runtimeReady: "代理服务运行正常", line: "连接线路", routeMode: "代理方式", smartRouting: "智能分流（绕过中国大陆）", connectNow: "立即连接", disconnect: "断开连接", accountOverview: "账户概览", traffic: "流量用量", todayTraffic: "当日流量", used: "过去已用", remaining: "剩余流量", expiry: "到期时间", unlimited: "不限量", neverExpires: "不会过期",
			chooseLine: "选择线路", lines: "线路", updateLines: "更新线路", useLine: "使用", inUse: "使用中", noLines: "暂无线可用线路，请先更新线路。", updating: "正在安全更新线路…", updateSuccess: "线路更新完成", updateFailed: "线路更新失败，原有连接未被破坏。",
			devicePreferences: "设备偏好", settings: "设置", autoConnect: "自动连接", autoConnectHint: "路由器启动后恢复上次使用的线路。", protection: "国内网络故障保护", protectionHint: "节点连续异常时撤销代理规则，优先保障国内网站与局域网。", gameUdp: "游戏 UDP 转发", gameUdpHint: "由 SSR Plus 根据当前线路协议自动管理。", automatic: "自动", autoUpdate: "自动更新线路", autoUpdateHint: "按本地时间定时更新面板订阅。", updateTime: "更新时间", updateTimeHint: "建议在网络空闲时执行。", saveSettings: "保存设置", updateNow: "立即更新", maintenance: "高级管理", maintenanceHint: "仅供维护人员进入原 LuCI / SSR Plus 后台。", maintenanceEntry: "维护入口", securityNote: "浏览器只显示脱敏账户信息、线路名称与运行状态，不显示订阅地址或节点密钥。",
			saved: "设置已保存", connecting: "正在连接并验证…", connectionFailed: "线路启动验证失败，已恢复原配置。", requestFailed: "操作失败，请稍后重试。", authRequired: "本机登录状态已失效，请重新登录。", loginFailed: "账号、密码或验证码不正确。", accountBlocked: "该账户当前不可连接。", noSelection: "请先选择一条线路。"
		},
		en: {
			secureRouter: "SECURE ROUTER", heroTitle: "Router connectivity,<br>as simple as an app", heroText: "Sign in with your panel account, choose a line and connect. Complex networking stays safely managed by the router.",
			deviceConsole: "DEVICE CONSOLE", loginDevice: "Sign in", loginHint: "Use your EzIPLC account to manage this HKC router.", email: "Email", password: "Password", totp: "Authenticator code (if enabled)", login: "Sign in and bind", privacy: "The account token is stored with restricted permissions on the router. Subscription URLs and node keys are never exposed to this page.",
			routerOnline: "Router online", connectionCenter: "CONNECTION CENTER", home: "Home", refresh: "Refresh", disconnected: "Disconnected", connected: "Connected", protected: "Domestic network protected", ready: "Ready", runtimeReady: "Proxy service is healthy", line: "Line", routeMode: "Routing", smartRouting: "Smart routing (bypass mainland China)", connectNow: "Connect now", disconnect: "Disconnect", accountOverview: "ACCOUNT OVERVIEW", traffic: "Traffic usage", todayTraffic: "Today", used: "Used", remaining: "Remaining", expiry: "Expires", unlimited: "Unlimited", neverExpires: "Never",
			chooseLine: "CHOOSE A LINE", lines: "Lines", updateLines: "Update lines", useLine: "Use", inUse: "In use", noLines: "No line is available. Update lines first.", updating: "Updating lines safely…", updateSuccess: "Lines updated", updateFailed: "Line update failed. The existing connection was preserved.",
			devicePreferences: "DEVICE PREFERENCES", settings: "Settings", autoConnect: "Auto connect", autoConnectHint: "Restore the last line after the router starts.", protection: "Domestic network protection", protectionHint: "Withdraw proxy rules after repeated node failures to preserve domestic and LAN access.", gameUdp: "Game UDP forwarding", gameUdpHint: "Managed automatically by SSR Plus for the selected protocol.", automatic: "Automatic", autoUpdate: "Auto update lines", autoUpdateHint: "Update the panel subscription on a local schedule.", updateTime: "Update time", updateTimeHint: "Choose a quiet time.", saveSettings: "Save settings", updateNow: "Update now", maintenance: "Advanced management", maintenanceHint: "Original LuCI / SSR Plus access for maintainers only.", maintenanceEntry: "Maintenance", securityNote: "The browser receives only masked account data, line names and status—never subscription URLs or node secrets.",
			saved: "Settings saved", connecting: "Connecting and validating…", connectionFailed: "Runtime validation failed. The previous configuration was restored.", requestFailed: "The request failed. Try again later.", authRequired: "The local session expired. Sign in again.", loginFailed: "Incorrect account, password or verification code.", accountBlocked: "This account cannot currently connect.", noSelection: "Choose a line first."
		}
	}[locale];

	let status = null;
	let lines = [];
	let busy = false;

	function t(key) { return copy[key] || key; }
	function applyI18n() {
		document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
		document.querySelectorAll("[data-i18n]").forEach((node) => {
			const value = t(node.dataset.i18n);
			if (node.dataset.i18n === "heroTitle") node.innerHTML = value;
			else node.textContent = value;
		});
	}

	function csrf() {
		const item = document.cookie.split(";").map((v) => v.trim()).find((v) => v.startsWith("hkc_csrf="));
		return item ? item.slice("hkc_csrf=".length) : "";
	}

	async function request(path, options) {
		const config = Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options || {});
		if (config.method && config.method !== "GET") {
			config.headers["Content-Type"] = "application/json";
			config.headers["X-HKC-CSRF"] = csrf();
		}
		const response = await fetch(API + path, config);
		const payload = await response.json().catch(() => ({ ok: false, error: "invalid_response" }));
		if (!response.ok || !payload.ok) {
			const error = new Error(payload.error || "request_failed");
			error.status = response.status;
			throw error;
		}
		return payload.data;
	}

	function notify(message, error) {
		const node = $("toast");
		node.textContent = message;
		node.classList.toggle("error", !!error);
		node.classList.add("show");
		window.clearTimeout(notify.timer);
		notify.timer = window.setTimeout(() => node.classList.remove("show"), 3200);
	}

	function friendlyError(error) {
		if (error.status === 401 && error.message === "authentication_required") return t("authRequired");
		if (["credentials_required", "credentials_invalid", "MFA_REQUIRED", "MFA_INVALID", "invalid_mfa_code"].includes(error.message)) return t("loginFailed");
		if (error.message === "account_cannot_connect") return t("accountBlocked");
		if (error.message === "runtime_validation_failed") return t("connectionFailed");
		return t("requestFailed");
	}

	function bytes(value) {
		let amount = Number(value) || 0;
		const units = ["B", "KB", "MB", "GB", "TB"];
		let unit = 0;
		while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
		return `${amount >= 100 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
	}

	function selectedId() {
		return status && status.selectedNode ? status.selectedNode.id : "";
	}

	function renderLines() {
		const select = $("homeLine");
		const previous = select.value || selectedId();
		select.replaceChildren();
		lines.forEach((line) => {
			const option = document.createElement("option");
			option.value = line.id;
			option.textContent = `${line.name} · ${line.protocol || "PROXY"}`;
			select.appendChild(option);
		});
		if (lines.some((line) => line.id === previous)) select.value = previous;
		select.disabled = lines.length === 0;

		const list = $("lineList");
		list.replaceChildren();
		if (!lines.length) {
			const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = t("noLines"); list.appendChild(empty); return;
		}
		lines.forEach((line) => {
			const card = document.createElement("article"); card.className = `line-card${line.id === selectedId() ? " selected" : ""}`;
			const info = document.createElement("div"); info.className = "line-info";
			const name = document.createElement("strong"); name.textContent = line.name;
			const protocol = document.createElement("small"); protocol.textContent = line.protocol || "PROXY";
			info.append(name, protocol);
			const button = document.createElement("button"); button.type = "button"; button.className = line.id === selectedId() ? "secondary compact" : "primary compact"; button.textContent = line.id === selectedId() ? t("inUse") : t("useLine"); button.disabled = busy || (line.id === selectedId() && status.running);
			button.addEventListener("click", () => connect(line.id));
			card.append(info, button); list.appendChild(card);
		});
	}

	function renderStatus() {
		if (!status) return;
		const connected = !!status.running;
		$("connectionCard").classList.toggle("connected", connected);
		$("connectionCard").classList.toggle("offline", !connected);
		$("stateBadge").textContent = connected ? "ONLINE" : (status.connectionState === "protected" ? "SAFE" : "OFFLINE");
		$("stateTitle").textContent = connected ? t("connected") : (status.connectionState === "protected" ? t("protected") : t("disconnected"));
		$("stateHint").textContent = connected && status.selectedNode ? `${status.selectedNode.name} · ${status.selectedNode.protocol}` : t("ready");
		$("connectButton").textContent = connected ? t("disconnect") : t("connectNow");
		$("connectButton").disabled = busy || (!connected && lines.length === 0);
		const usage = status.account && status.account.usage ? status.account.usage : {};
		$("todayUsed").textContent = bytes(usage.todayUsed);
		$("usedTraffic").textContent = bytes(usage.used);
		$("remainingTraffic").textContent = usage.isUnlimited ? t("unlimited") : bytes(usage.remaining);
		$("expireAt").textContent = usage.isUnlimited ? t("neverExpires") : (usage.expireAt || "--");
		$("accountIdentity").textContent = [status.account && status.account.name, status.account && status.account.email].filter(Boolean).join(" · ");
		const ratio = usage.isUnlimited || !Number(usage.total) ? 0 : Math.min(100, Math.max(0, Number(usage.used) / Number(usage.total) * 100));
		$("usageBar").style.width = `${ratio}%`;
		if (status.settings) {
			$("autoConnect").checked = !!status.settings.autoConnect;
			$("domesticProtection").checked = !!status.settings.domesticProtection;
			$("autoUpdate").checked = !!status.settings.autoUpdate;
			$("updateHour").value = String(status.settings.updateHour);
			$("updateMinute").value = String(status.settings.updateMinute);
		}
		renderLines();
	}

	async function loadAll() {
		const results = await Promise.all([request("status"), request("lines")]);
		status = results[0]; lines = results[1] || []; renderStatus();
	}

	async function connect(nodeId) {
		if (!nodeId || busy) return notify(t("noSelection"), true);
		busy = true; renderStatus(); notify(t("connecting"));
		try {
			status = await request("connect", { method: "POST", body: JSON.stringify({ nodeId }) });
			lines = await request("lines"); renderStatus();
		} catch (error) { notify(friendlyError(error), true); }
		finally { busy = false; renderStatus(); }
	}

	async function disconnect() {
		if (busy) return;
		busy = true; renderStatus();
		try { status = await request("disconnect", { method: "POST", body: "{}" }); renderStatus(); }
		catch (error) { notify(friendlyError(error), true); }
		finally { busy = false; renderStatus(); }
	}

	async function waitForSync() {
		let result = { state: "running" };
		for (let i = 0; i < 60 && ["queued", "running", "busy"].includes(result.state); i += 1) {
			await new Promise((resolve) => setTimeout(resolve, 1000));
			result = await request("sync/status");
		}
		if (result.state !== "success") throw new Error("sync_failed");
		await loadAll(); $("syncMessage").textContent = t("updateSuccess"); notify(t("updateSuccess"));
	}

	async function syncLines() {
		if (busy) return;
		busy = true; $("syncMessage").textContent = t("updating"); renderStatus();
		try {
			await request("sync", { method: "POST", body: "{}" });
			await waitForSync();
		} catch (error) { $("syncMessage").textContent = t("updateFailed"); notify(t("updateFailed"), true); }
		finally { busy = false; renderStatus(); }
	}

	function fillTimes() {
		for (let hour = 0; hour < 24; hour += 1) { const option = document.createElement("option"); option.value = String(hour); option.textContent = String(hour).padStart(2, "0"); $("updateHour").appendChild(option); }
		[0, 15, 30, 45].forEach((minute) => { const option = document.createElement("option"); option.value = String(minute); option.textContent = String(minute).padStart(2, "0"); $("updateMinute").appendChild(option); });
	}

	function showLogin() { $("loginView").classList.remove("hidden"); $("appView").classList.add("hidden"); }
	function showApp() { $("loginView").classList.add("hidden"); $("appView").classList.remove("hidden"); }

	function bindEvents() {
		$("loginForm").addEventListener("submit", async (event) => {
			event.preventDefault(); const button = event.submitter; button.disabled = true;
			try {
				await request("login", { method: "POST", body: JSON.stringify({ email: $("email").value, password: $("password").value, mfaCode: $("mfaCode").value }) });
				$("password").value = ""; showApp(); await loadAll();
				waitForSync().catch(() => { $("syncMessage").textContent = t("updateFailed"); });
			} catch (error) { notify(friendlyError(error), true); }
			finally { button.disabled = false; }
		});
		$("connectButton").addEventListener("click", () => status && status.running ? disconnect() : connect($("homeLine").value));
		$("refreshButton").addEventListener("click", () => loadAll().catch((error) => notify(friendlyError(error), true)));
		$("syncButton").addEventListener("click", syncLines); $("syncNowButton").addEventListener("click", syncLines);
		$("settingsForm").addEventListener("submit", async (event) => {
			event.preventDefault(); const button = event.submitter; button.disabled = true;
			try {
				const settings = await request("settings/update", { method: "POST", body: JSON.stringify({ autoConnect: $("autoConnect").checked, domesticProtection: $("domesticProtection").checked, autoUpdate: $("autoUpdate").checked, updateHour: Number($("updateHour").value), updateMinute: Number($("updateMinute").value) }) });
				status.settings = settings; renderStatus(); notify(t("saved"));
			} catch (error) { notify(friendlyError(error), true); }
			finally { button.disabled = false; }
		});
		$("logoutButton").addEventListener("click", async () => { try { await request("logout", { method: "POST", body: "{}" }); } catch (_) {} status = null; lines = []; showLogin(); });
		document.querySelectorAll(".bottom-nav button").forEach((button) => button.addEventListener("click", () => {
			document.querySelectorAll(".page,.bottom-nav button").forEach((node) => node.classList.remove("active"));
			$(button.dataset.page).classList.add("active"); button.classList.add("active");
		}));
	}

	async function boot() {
		applyI18n(); fillTimes(); bindEvents();
		try {
			const data = await request("bootstrap");
			if (!data.authenticated) return showLogin();
			status = data.data; showApp(); lines = await request("lines"); renderStatus();
		} catch (error) { showLogin(); notify(friendlyError(error), true); }
	}

	document.addEventListener("DOMContentLoaded", boot);
}());
