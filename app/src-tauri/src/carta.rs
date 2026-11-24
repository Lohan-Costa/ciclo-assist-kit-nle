//! A JANELA DA CARTA ABERTA (fase C2 do plano `docs/plano/2026-11-11-carta-aberta.md`): o botão abaixo de "Fluxos e
//! Agentes". O formato é o da `oficina.rs`: uma webview só, servida pelo serviço do Assist (`/carta`).
//! ⛔ A página é REMOTA e não ganha IPC (`capabilities/default.json`), como os painéis dos módulos.
//!
//! ⭐ A diferença: ela RECEBE o arrasto da bin do MC e do Premiere (é o "mandar"). No Mac o tratador do Tauri fica
//! ligado e o `arrasto_mac` registra os tipos do MC e do Premiere; no Windows o tratador fica desligado (o WebView2
//! pediria o arquivo e o MC EXPORTARIA) e o `arrasto_win` põe o alvo OLE. Os dois avisam `window.cartaArrasto`.

use tauri::window::Color;
use tauri::{Manager, WebviewUrl};

use crate::registro::registrar;
use crate::EstadoApp;

pub(crate) const JANELA: &str = "carta";
const ENDERECO: &str = "http://127.0.0.1:7824/carta";
const FUNCAO_DO_ARRASTO: &str = "cartaArrasto";
const LARGURA: f64 = 1150.0;
const ALTURA: f64 = 730.0;
/// O fundo antes de a página chegar: a moldura escura do `carta.css`, senão a janela pisca branco.
const FUNDO: Color = Color(43, 43, 43, 255);

/// Abre a janela, ou a traz para a frente.
pub(crate) fn abrir(app: &tauri::AppHandle) -> Result<(), String> {
    registrar("carta aberta: abrir");
    if let Some(j) = app.get_webview_window(JANELA) {
        let _ = j.unminimize();
        let _ = j.show();
        let _ = j.set_focus();
        return Ok(());
    }
    let url: tauri::Url = ENDERECO.parse().map_err(|e| format!("{e}"))?;
    let fixada = app.state::<EstadoApp>().0.lock().unwrap().fixada;
    let construtor = tauri::webview::WebviewWindowBuilder::new(app, JANELA, WebviewUrl::External(url))
        .title("Ciclo Assist — Carta Aberta")
        .inner_size(LARGURA, ALTURA)
        .min_inner_size(900.0, 520.0)
        .resizable(true)
        .always_on_top(fixada)
        .background_color(FUNDO)
        .visible(false);
    // ⚠️ No Windows o tratador do WebView2 fica DESLIGADO (o `arrasto_win` é quem recebe); no Mac, LIGADO (o wry
    //    repassa ao `arrasto_mac`), como nas webviews de módulo da janela principal (`lib.rs`, `criar_janela`).
    let construtor = if cfg!(target_os = "macos") { construtor } else { construtor.disable_drag_drop_handler() };
    let janela = construtor.build().map_err(|e| format!("não consegui abrir a Carta Aberta: {e}"))?;
    #[cfg(target_os = "macos")]
    crate::arrasto_mac::instalar_na_janela(janela.as_ref(), FUNCAO_DO_ARRASTO);
    #[cfg(windows)]
    crate::arrasto_win::instalar_na_janela(&janela.as_ref().window(), janela.as_ref(), FUNCAO_DO_ARRASTO);
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
