// O painel CARREGA sem erro (tests/test_painel_carrega.py). Um DOM falso que aceita tudo: o que
// se pega aqui é erro de JavaScript no carregamento, não de tela. Uso: node painel_boot.js <painel.js> <nle>
const fs = require("fs");
const erros = [];
process.on("unhandledRejection", (e) => { if (!/fetch|serviço/i.test(String(e && e.message))) erros.push("async: " + (e && e.stack || e)); });
const el = () => new Proxy(function () {}, {
  get: (t, k) => k === "children" ? [] : k === "classList" ? { toggle() {}, add() {}, remove() {}, contains() { return false; } }
    : k === "dataset" ? {} : k === "style" ? {} : k === Symbol.iterator ? function* () {} : k === "value" ? ""
    : k === "querySelectorAll" ? () => [] : k === "closest" ? () => null : k === "then" ? undefined
    : typeof k === "symbol" ? undefined
    : ["textContent", "innerHTML", "title", "className", "innerText", "id"].includes(k) ? ""
    : ["hidden", "disabled", "checked"].includes(k) ? false
    : ["offsetHeight", "offsetWidth", "offsetLeft", "offsetTop", "scrollLeft", "clientWidth", "length"].includes(k) ? 0 : el(),
  set: () => true, apply: () => el(),
});
global.window = global; global.addEventListener = () => {};   // o `resize` da barra fixa (2026-10-06)
global.document = { getElementById: el, querySelector: el, querySelectorAll: () => [], addEventListener() {}, body: el(), documentElement: el(), createElement: el };
global.location = { search: "?nle=" + (process.argv[3] || "mc"), origin: "http://127.0.0.1:7823" };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.fetch = () => Promise.reject(new Error("fetch falso"));
global.setInterval = () => 0; global.setTimeout = (f) => 0; global.getComputedStyle = () => ({});
global.URLSearchParams = URLSearchParams; global.EventSource = function () { return el(); };
global.navigator = { platform: "Win32", userAgent: "" };
try { eval(fs.readFileSync(process.argv[2], "utf8")); console.log("carregou"); } catch (e) { erros.push("sync: " + e.stack.split("\n").slice(0, 3).join(" | ")); }
setImmediate(() => setImmediate(() => { console.log(erros.length ? erros.join("\n") : "sem erros"); }));
