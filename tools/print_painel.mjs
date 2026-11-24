// Abre o painel no Edge headless, executa passos e salva prints. Uso: node print_painel.mjs <saida-base> <largura>
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , base = "painel", largura = "440"] = process.argv;
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const perfil = mkdtempSync(join(tmpdir(), "edge-"));
const porta = 9333;
const proc = spawn(edge, ["--headless=new", `--remote-debugging-port=${porta}`, `--user-data-dir=${perfil}`,
  `--window-size=${largura},620`, "--force-device-scale-factor=1", "about:blank"], { stdio: "ignore" });

const espera = (ms) => new Promise((r) => setTimeout(r, ms));
let alvos;
for (let i = 0; i < 40; i++) {
  try { alvos = await (await fetch(`http://127.0.0.1:${porta}/json`)).json(); break; } catch { await espera(250); }
}
const pagina = alvos.find((t) => t.type === "page");
const ws = new WebSocket(pagina.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pendentes = new Map();
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pendentes.has(m.id)) { pendentes.get(m.id)(m); pendentes.delete(m.id); }
});
const cdp = (method, params = {}) => new Promise((r) => { const i = ++id; pendentes.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result;
const print = async (nome) => {
  const r = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${base}-${nome}.png`, Buffer.from(r.result.data, "base64"));
  console.log("salvo", `${base}-${nome}.png`);
};

await cdp("Emulation.setDeviceMetricsOverride", { width: Number(largura), height: 620, deviceScaleFactor: 1, mobile: false });
await cdp("Page.navigate", { url: "http://127.0.0.1:7824/painel" });
await espera(2500);
console.log("erros:", JSON.stringify((await js("window.__erros || null")).result));
await js(`document.querySelector('[data-tela="vetores"]').click()`);
await espera(3000);
// rola a tela até a tabela
await js(`document.querySelector('.vet-tags').scrollIntoView({block:'start'})`);
await espera(400);
await print("1-tabela");
// ordena por Fala (duas vezes: desc padrão para número), liga "som" + "sem transcrição"
await js(`[...document.querySelectorAll('#vetCabeca button')].find(b=>b.textContent.startsWith('Fala')).click()`);
await js(`[...document.querySelectorAll('.vet-tag')].find(b=>b.textContent.startsWith('decupada')).click()`);
await espera(300);
await js(`document.querySelector('.vet-tags').scrollIntoView({block:'start'})`);
await js(`document.querySelector('.vet-rolagem').scrollLeft = 160`);
await espera(300);
await print("2-ordenada-filtrada");
console.log("estado:", JSON.stringify((await js(`({linhas: document.querySelectorAll('#vetores tr').length,
  cabeca: [...document.querySelectorAll('#vetCabeca button')].map(b=>b.textContent+(b.dataset.ordem||'')),
  botoes: [...document.querySelectorAll('.vet-acoes .botao')].map(b=>b.textContent.trim()),
  largura: document.querySelector('.vet-tabela').scrollWidth, caixa: document.querySelector('.vet-rolagem').clientWidth})`)).result.value));
ws.close();
proc.kill();
process.exit(0);
