//! A JANELA DE CONFIGURAÇÕES — a engrenagem abre uma janela própria (autor, 2026-11-07: "ao clicar na engrenagem
//! devemos ter uma janela nova, e não ficar restrito ao layout do app; assim podemos diagramar melhor os settings").
//!
//! ⭐ Uma janela para tudo, com a coluna lateral: **Geral** e **Integrações** (do app) e uma seção por módulo
//! (**Preparar · Assistir · Conformar · Entregar**). ⭐ Abre SEMPRE em Geral (autor, 2026-11-07; antes abria na seção
//! da aba que estava na tela).
//!
//! ⭐ Desenho: a página LOCAL `ui/ajustes.html` ocupa a janela inteira (a coluna, e o conteúdo de Geral e Integrações).
//! A seção de um módulo é uma webview FILHA por cima da área de conteúdo, com a tela de ajustes do próprio módulo
//! (`?ajustes=1` — o módulo continua dono dos ajustes dele; decisão do autor: reaproveitar agora, rediagramar depois).
//! ⭐ Carregadas ESCONDIDAS quando a janela abre, com o fundo escuro (autor, 2026-11-07: "ao clicar em qualquer aba pela
//! primeira vez a janela pisca branco, como se estivesse sendo criada na hora" — e estava: a webview nascia no clique,
//! branca até a página chegar). O primeiro clique só MOSTRA a pré-carregada; os seguintes recarregam (o motor pode ter
//! sido religado, e os ajustes leem o estado ao abrir).
//!
//! ⛔ As páginas dos módulos são REMOTAS e não ganham IPC (como na janela principal). E elas NÃO trabalham no modo
//! `?ajustes=1`: a cópia do Sincronizar tiraria da fila `/nlejob` o trabalho da aba Preparar.

use std::collections::HashSet;
use std::sync::Mutex;

use tauri::window::Color;
use tauri::{LogicalPosition, LogicalSize, Manager, WebviewUrl};

use crate::registro::registrar;
use crate::{barra_de_titulo, porta_ocupada, EstadoApp, Modulo};

pub(crate) const JANELA: &str = "ajustes";
/// A página local (a coluna e as seções do app).
const MENU: &str = "ajustes-menu";
/// A largura da coluna lateral, em pixels lógicos — a MESMA do `ui/ajustes.css` (`--coluna`).
const COLUNA: f64 = 208.0;
const LARGURA: f64 = 920.0;
const ALTURA: f64 = 660.0;
/// O fundo das páginas ANTES de carregarem — o `--fundo` do `ui/ajustes.css` e do `integracoes.css` (#1c1c1c).
const FUNDO: Color = Color(28, 28, 28, 255);
/// As seções pré-carregadas que o editor ainda não abriu: o primeiro clique só mostra, sem recarregar.
static NAO_VISTAS: Mutex<Option<HashSet<String>>> = Mutex::new(None);

/// As seções servidas por um MOTOR (webview por cima da área de conteúdo): os módulos e as Integrações, que são do
/// serviço do Assist (`/integracoes`, a lógica do instalador único em Python).
const REMOTAS: [&str; 5] = ["preparar", "assistir", "conformar", "integracoes", "conta"];

fn rotulo_da_webview(secao: &str) -> String {
    format!("ajustes-{secao}")
}

/// A porta e o caminho da seção remota; `None` = a página local desenha (Geral, Entregar).
fn endereco(secao: &str) -> Option<(u16, &'static str)> {
    match secao {
        "integracoes" => Some((7824, "/integracoes")),
        // ⭐ A conta Claude do app (2026-11-07, `cicloassist/conta.py`): também do serviço do Assist.
        "conta" => Some((7824, "/conta")),
        _ => Modulo::de(secao).and_then(caminho_dos_ajustes),
    }
}

/// O caminho da tela de ajustes de cada módulo, no motor dele. `None` = o módulo ainda não tem motor (Entregar).
pub(crate) fn caminho_dos_ajustes(m: Modulo) -> Option<(u16, &'static str)> {
    match m {
        Modulo::Preparar => Some((7817, "/avid/panel?casca=app&embutido=1&ajustes=1")),
        Modulo::Assistir => Some((7824, "/painel?casca=app&embutido=1&ajustes=1")),
        Modulo::Conformar => Some((7823, "/painel?nle=mc&casca=app&embutido=1&ajustes=1")),
        Modulo::Entregar => None,
    }
}

/// Abre a janela (ou a traz para a frente) na seção pedida. `secao` = `geral`, `integracoes` ou o rótulo de um módulo.
pub(crate) fn abrir(app: &tauri::AppHandle, secao: &str) -> Result<(), String> {
    registrar(&format!("configurações: abrir em {secao}"));
    if let Some(j) = app.get_window(JANELA) {
        let _ = j.unminimize();
        let _ = j.show();
        let _ = j.set_focus();
        if let Some(menu) = app.get_webview(MENU) {
            let _ = menu.eval(format!("window.irPara && window.irPara({})", serde_json::json!(secao)));
        }
        return Ok(());
    }
    let fixada = app.state::<EstadoApp>().0.lock().unwrap().fixada;
    let janela = tauri::window::WindowBuilder::new(app, JANELA)
        .title("Ciclo Assist — Configurações")
        .inner_size(LARGURA, ALTURA)
        .min_inner_size(640.0, 420.0)
        .resizable(true)
        .always_on_top(fixada)
        .background_color(FUNDO)
        .visible(false)
        .build()
        .map_err(|e| format!("não consegui abrir as configurações: {e}"))?;
    posicionar(app, &janela);
    let (w, h) = tamanho_logico(&janela);
    let t = barra_de_titulo(&janela);
    let pagina = format!("ajustes.html?s={}", secao);
    janela
        .add_child(
            tauri::webview::WebviewBuilder::new(MENU, WebviewUrl::App(pagina.into()))
                .disable_drag_drop_handler()
                .background_color(FUNDO),
            LogicalPosition::new(0.0, t),
            LogicalSize::new(w, (h - t).max(0.0)),
        )
        .map_err(|e| format!("não consegui criar a página das configurações: {e}"))?;
    // ⭐ As seções remotas nascem agora, escondidas, com a janela ainda invisível: nada pisca.
    *NAO_VISTAS.lock().unwrap() = Some(HashSet::new());
    for s in REMOTAS {
        if let Some((porta, _)) = endereco(s) {
            if porta_ocupada(porta) && criar_secao(&janela, s).is_ok() {
                NAO_VISTAS.lock().unwrap().get_or_insert_with(HashSet::new).insert(s.to_string());
            }
        }
    }
    let _ = janela.show();
    let _ = janela.set_focus();
    Ok(())
}

/// Ao lado da janela principal (à direita, se couber; senão à esquerda), no mesmo monitor; senão, o meio da tela.
fn posicionar(app: &tauri::AppHandle, janela: &tauri::Window) {
    use tauri::{PhysicalPosition, PhysicalSize};
    let Some(m) = janela.primary_monitor().ok().flatten() else { return };
    let esc = m.scale_factor();
    let principal = app.get_window(crate::JANELA);
    let monitor = principal.as_ref().and_then(|p| p.current_monitor().ok().flatten()).unwrap_or(m);
    let a = *monitor.work_area();
    let w = ((LARGURA * esc) as u32).min(a.size.width);
    let h = ((ALTURA * esc) as u32).min(a.size.height);
    let _ = janela.set_size(PhysicalSize::new(w, h));
    let (fim_x, fim_y) = (a.position.x + a.size.width as i32, a.position.y + a.size.height as i32);
    let meio = (a.position.x + (a.size.width.saturating_sub(w) / 2) as i32,
                a.position.y + (a.size.height.saturating_sub(h) / 2) as i32);
    let (x, y) = principal
        .and_then(|p| Some((p.outer_position().ok()?, p.outer_size().ok()?)))
        .map(|(pp, ps)| {
            let direita = pp.x + ps.width as i32 + 8;
            let esquerda = pp.x - w as i32 - 8;
            let x = if direita + w as i32 <= fim_x {
                direita
            } else if esquerda >= a.position.x {
                esquerda
            } else {
                meio.0
            };
            (x, pp.y.clamp(a.position.y, (fim_y - h as i32).max(a.position.y)))
        })
        .unwrap_or(meio);
    let _ = janela.set_position(PhysicalPosition::new(x, y));
}

fn tamanho_logico(janela: &tauri::Window) -> (f64, f64) {
    let escala = janela.scale_factor().unwrap_or(1.0);
    janela
        .inner_size()
        .map(|t| (t.width as f64 / escala, t.height as f64 / escala))
        .unwrap_or((LARGURA, ALTURA))
}

/// A página local por inteiro; a seção do módulo à direita da coluna. Chamado a cada mudança de tamanho.
pub(crate) fn arrumar(app: &tauri::AppHandle) {
    let Some(janela) = app.get_window(JANELA) else { return };
    let (w, h) = tamanho_logico(&janela);
    let t = barra_de_titulo(&janela);
    let alto = (h - t).max(0.0);
    if let Some(menu) = app.get_webview(MENU) {
        let _ = menu.set_position(LogicalPosition::new(0.0, t));
        let _ = menu.set_size(LogicalSize::new(w, alto));
    }
    for secao in REMOTAS {
        if let Some(wv) = app.get_webview(&rotulo_da_webview(secao)) {
            let _ = wv.set_position(LogicalPosition::new(COLUNA, t));
            let _ = wv.set_size(LogicalSize::new((w - COLUNA).max(0.0), alto));
        }
    }
}

/// Mostra a seção pedida. Devolve o que a página local tem de fazer: `"local"` (Geral, Entregar — ela mesma
/// desenha), `"modulo"` (a webview do motor está por cima) ou `"fora"` (o motor da seção não está no ar).
pub(crate) fn mostrar_secao(app: &tauri::AppHandle, secao: &str) -> Result<&'static str, String> {
    let alvo = endereco(secao);
    // esconde as das outras seções
    for outra in REMOTAS {
        if outra != secao || alvo.is_none() {
            if let Some(wv) = app.get_webview(&rotulo_da_webview(outra)) {
                let _ = wv.hide();
            }
        }
    }
    let Some((porta, caminho)) = alvo else { return Ok("local") };
    let rotulo = rotulo_da_webview(secao);
    if !porta_ocupada(porta) {
        if let Some(wv) = app.get_webview(&rotulo) {
            let _ = wv.hide();
        }
        return Ok("fora");
    }
    let url: tauri::Url = format!("http://127.0.0.1:{porta}{caminho}").parse().map_err(|e| format!("{e}"))?;
    if let Some(wv) = app.get_webview(&rotulo) {
        // ⭐ Pré-carregada e ainda não vista: só mostra. Senão, recarrega (o motor pode ter sido religado).
        let primeira = NAO_VISTAS.lock().unwrap().as_mut().map(|n| n.remove(secao)).unwrap_or(false);
        if !primeira {
            let _ = wv.navigate(url);
        }
        let _ = wv.show();
        let _ = wv.set_focus();
        return Ok("modulo");
    }
    let janela = app.get_window(JANELA).ok_or("a janela de configurações não está aberta")?;
    let wv = criar_secao(&janela, secao)?;
    let _ = wv.show();
    Ok("modulo")
}

/// A webview de uma seção remota, ESCONDIDA e com o fundo escuro (o branco do clarão era o fundo padrão dela).
fn criar_secao(janela: &tauri::Window, secao: &str) -> Result<tauri::Webview, String> {
    let (porta, caminho) = endereco(secao).ok_or("seção sem endereço")?;
    let url: tauri::Url = format!("http://127.0.0.1:{porta}{caminho}").parse().map_err(|e| format!("{e}"))?;
    let (w, h) = tamanho_logico(janela);
    let t = barra_de_titulo(janela);
    let wv = janela
        .add_child(
            tauri::webview::WebviewBuilder::new(rotulo_da_webview(secao), WebviewUrl::External(url))
                .disable_drag_drop_handler()
                .background_color(FUNDO),
            LogicalPosition::new(COLUNA, t),
            LogicalSize::new((w - COLUNA).max(0.0), (h - t).max(0.0)),
        )
        .map_err(|e| format!("não consegui abrir a seção {secao}: {e}"))?;
    let _ = wv.hide();
    Ok(wv)
}

/// O pino da janela principal vale para esta também: fixada, a principal ficaria por cima dos ajustes.
pub(crate) fn acompanhar_o_pino(app: &tauri::AppHandle, sim: bool) {
    if let Some(j) = app.get_window(JANELA) {
        let _ = j.set_always_on_top(sim);
    }
}

#[cfg(test)]
mod testes {
    use super::*;

    #[test]
    fn toda_secao_remota_tem_endereco_e_as_locais_nao() {
        for secao in REMOTAS {
            assert!(endereco(secao).is_some(), "{secao}");
        }
        assert_eq!(endereco("geral"), None);
        assert_eq!(endereco("entregar"), None);
        assert_eq!(endereco("integracoes"), Some((7824, "/integracoes")));
    }

    #[test]
    fn os_ajustes_de_cada_modulo_moram_no_motor_dele() {
        for m in Modulo::TODOS {
            match (m.motor(), caminho_dos_ajustes(m)) {
                (Some((p, _)), Some((q, caminho))) => {
                    assert_eq!(p, q, "{m:?}");
                    assert!(caminho.contains("ajustes=1"), "{caminho}");
                    assert!(caminho.contains("embutido=1"), "{caminho}");
                }
                (None, None) => {}
                outro => panic!("{m:?}: {outro:?}"),
            }
        }
    }
}
