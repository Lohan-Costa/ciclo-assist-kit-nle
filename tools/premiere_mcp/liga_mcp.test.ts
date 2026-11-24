// Ciclo Assist, 2026-11-06: catálogo MCP do Premiere + override da beta feature do servidor MCP "user".
// ⛔ no Windows (27.1) o Test Host checa o tipo: sem a declaração, TS2304 e o script nem roda (2026-11-18)
declare const __dirname: string | undefined;
setExpectedRuntime(2, "minutes");
// ⚠️ Pasta de saída: a MESMA pasta deste script (o Test Host Plugin roda com acesso ao disco).
const OUT = (typeof __dirname !== "undefined" ? __dirname : ".") + "/";
function grava(nome: string, texto: string) {
  const fs = require("fs");
  try { fs.writeFileSync(OUT + nome, texto, { encoding: "utf-8" }); }
  catch (e) { fs.writeFileSync("file:" + OUT + nome, texto, { encoding: "utf-8" }); }
}
describe("ciclo mcp", () => {
  it("lista e liga", async () => {
    const uxp: any = require("uxp");
    const rel: any = {};
    const bf: any = uxp.dvaappsupport && uxp.dvaappsupport.BetaFeature;
    const mcp: any = uxp.hSLScripting && uxp.hSLScripting.MCP;
    rel.temBetaFeature = !!bf; rel.temMCP = !!mcp;
    rel.interno = bf ? bf.isEntitlementSetToInternalFeaturesAllowed : null;
    const flags = ["PPro.MCP.EnableMCPServer","PPro.AIAssistant","PPro.AIAssistant.SupportsSubAgents","PPro.AIAssistant.SkillsWindow","PPro.AIAssistant.ComposerBar"];
    rel.antes = {}; for (const f of flags) { try { rel.antes[f] = bf.isFeatureEnabled(f); } catch (e) { rel.antes[f] = "erro: " + e; } }
    try { rel.prefsUser = Object.assign({}, mcp.getPreferences(), { accessToken: "(oculto)" }); } catch (e) { rel.prefsUser = "erro: " + e; }
    for (const ep of ["user", "assistant"]) {
      try { const t = await mcp.listMCPTools(ep); grava("tools_" + ep + ".json", typeof t === "string" ? t : JSON.stringify(t, null, 1)); rel["tools_" + ep] = "ok"; }
      catch (e) { rel["tools_" + ep] = "erro: " + e; }
    }
    try { rel.override = bf.setFeatureFlagOverride("PPro.MCP.EnableMCPServer", bf.FEATURE_FLAG_OVERRIDE_ON); } catch (e) { rel.override = "erro: " + e; }
    try { rel.depois = bf.isFeatureEnabled("PPro.MCP.EnableMCPServer"); } catch (e) { rel.depois = "erro: " + e; }
    try { rel.prefsAssistant = mcp.getAssistantPreferences(); if (rel.prefsAssistant) rel.prefsAssistant.accessToken = "(oculto)"; } catch (e) { rel.prefsAssistant = "erro: " + e; }
    try { rel.setPrefs = mcp.setPreferences({ enabled: true, authenticationMode: 1 }); } catch (e) { rel.setPrefs = "erro: " + e; }
    try { const pr = mcp.getPreferences(); grava("prefs_user.json", JSON.stringify(pr, null, 1)); rel.prefsDepois = Object.assign({}, pr, { accessToken: pr && pr.accessToken ? "(gravado em prefs_user.json)" : "" }); } catch (e) { rel.prefsDepois = "erro: " + e; }
    grava("relatorio.json", JSON.stringify(rel, null, 1));
    expect(rel.temBetaFeature).toBe(true);
  });
});
