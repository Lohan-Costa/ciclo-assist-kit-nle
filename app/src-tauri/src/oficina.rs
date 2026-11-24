//! A JANELA "FLUXOS E AGENTES" (fase B1 do plano `docs/plano/2026-11-08-agentes.md`): o botão à direita da linha do modelo.
//!
//! ⭐ Uma webview só, servida pelo serviço do Assist (`/oficina`): diferente das configurações, nada aqui é de outro módulo.
//! ⛔ A página é REMOTA e não ganha IPC (`capabilities/default.json`), como os painéis dos módulos.

use tauri::window::Color;
use tauri::{Manager, WebviewUrl};

use crate::registro::registrar;
use crate::EstadoApp;

pub(crate) const JANELA: &str = "oficina";
const ENDERECO: &str = "http://127.0.0.1:7824/oficina";
const LARGURA: f64 = 1150.0;
const ALTURA: f64 = 640.0;
/// O fundo antes de a página chegar: o `--fundo` do `oficina.css`, senão a janela pisca branco.
const FUNDO: Color = Color(43, 43, 43, 255);

/// Abre a janela, ou a traz para a frente.
pub(crate) fn abrir(app: &tauri::AppHandle) -> Result<(), String> {
    registrar("fluxos e agentes: abrir");
    if let Some(j) = app.get_webview_window(JANELA) {
        let _ = j.unminimize();
        let _ = j.show();
        let _ = j.set_focus();
        return Ok(());
    }
    let url: tauri::Url = ENDERECO.parse().map_err(|e| format!("{e}"))?;
    let fixada = app.state::<EstadoApp>().0.lock().unwrap().fixada;
    let janela = tauri::webview::WebviewWindowBuilder::new(app, JANELA, WebviewUrl::External(url))
        .title("Ciclo Assist — Fluxos e Agentes")
        .inner_size(LARGURA, ALTURA)
        .min_inner_size(900.0, 520.0)
        .resizable(true)
        .always_on_top(fixada)
        .background_color(FUNDO)
        .disable_drag_drop_handler()
        .visible(false)
        .build()
        .map_err(|e| format!("não consegui abrir Fluxos e Agentes: {e}"))?;
    centralizar(app, &janela);
    let _ = janela.show();
    let _ = janela.set_focus();
    Ok(())
}

/// No meio da ÁREA ÚTIL do monitor do app: sem a barra de tarefas, que cortava a parte de baixo da janela.
fn centralizar(app: &tauri::AppHandle, janela: &tauri::WebviewWindow) {
    use tauri::{PhysicalPosition, PhysicalSize};
    let monitor = app.get_window(crate::JANELA).and_then(|p| p.current_monitor().ok().flatten());
    let Some(m) = monitor.or_else(|| janela.primary_monitor().ok().flatten()) else { return };
    let a = *m.work_area();
    let esc = m.scale_factor();
    // A moldura conta: o `set_size` é da parte de dentro, e a barra de título fica por cima dela.
    let (dw, dh) = match (janela.outer_size().ok(), janela.inner_size().ok()) {
        (Some(f), Some(d)) => (f.width.saturating_sub(d.width), f.height.saturating_sub(d.height)),
        _ => (0, 0),
    };
    let w = ((LARGURA * esc) as u32).min(a.size.width.saturating_sub(dw));
    let h = ((ALTURA * esc) as u32).min(a.size.height.saturating_sub(dh));
    let _ = janela.set_size(PhysicalSize::new(w, h));
    let x = a.position.x + (a.size.width.saturating_sub(w + dw) / 2) as i32;
    let y = a.position.y + (a.size.height.saturating_sub(h + dh) / 2) as i32;
    let _ = janela.set_position(PhysicalPosition::new(x, y));
}

pub(crate) fn acompanhar_o_pino(app: &tauri::AppHandle, sim: bool) {
    if let Some(j) = app.get_webview_window(JANELA) {
        let _ = j.set_always_on_top(sim);
    }
}

pub(crate) fn fechar(app: &tauri::AppHandle) {
    if let Some(j) = app.get_webview_window(JANELA) {
        let _ = j.destroy();
    }
}
