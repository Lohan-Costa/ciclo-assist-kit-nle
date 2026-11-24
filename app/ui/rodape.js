/* O rodapé do guarda-chuva: o link do autor abre no navegador pelo Rust (endereço fixo no binário). */
"use strict";
var ponte = window.__TAURI__ && window.__TAURI__.core;
document.getElementById("autor").addEventListener("click", function () { if (ponte) { ponte.invoke("abrir_autor"); } });
if (ponte) {
  ponte.invoke("estado_do_topo").then(function (e) {
    document.getElementById("versao").textContent = "v" + e.versao;
  }, function () {});
}
