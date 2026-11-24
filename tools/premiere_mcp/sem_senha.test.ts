// Ciclo Assist, 2026-11-06: DESENVOLVIMENTO — desliga a autenticação do servidor MCP "user" do Premiere (só localhost).
// ⛔ no Windows (27.1) o Test Host checa o tipo: sem a declaração, TS2304 e o script nem roda (2026-11-18)
declare const __dirname: string | undefined;
setExpectedRuntime(1, "minutes");
describe("ciclo mcp", () => {
  it("sem senha", async () => {
    const uxp: any = require("uxp");
    const mcp: any = uxp.hSLScripting.MCP;
    const fs = require("fs");
    const rel: any = {};
    const antes = mcp.getPreferences(); rel.antes = Object.assign({}, antes, { accessToken: "(oculto)" });
    rel.set = mcp.setPreferences({ enabled: true, authenticationMode: 0 });
    const depois = mcp.getPreferences(); rel.depois = Object.assign({}, depois, { accessToken: "(oculto)" });
    fs.writeFileSync((typeof __dirname !== "undefined" ? __dirname : ".") + "/sem_senha.json", JSON.stringify(rel, null, 1), { encoding: "utf-8" });
    expect(rel.set).toBe(true);
  });
});
