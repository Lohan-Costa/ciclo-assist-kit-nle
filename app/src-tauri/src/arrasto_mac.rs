//! O arrasto na janela do Ciclo Assist no macOS — o gêmeo do `arrasto_win`.
//!
//! ⭐ Portado do De Lá Pra Cá (`_DeLaPraCa/app/src-tauri/src/arrasto_mac.rs`, 2026-10-24/25) em 2026-11-07, quando o
//! autor viu que o arrasto da bin do MC para a Preparar "não reconheceu o gesto" no Mac: o guarda-chuva só tinha o alvo
//! do Windows, e no Mac as webviews nasciam com o tratador do Tauri DESLIGADO e sem o tipo do MC registrado — a
//! miniatura passava por cima e nada acontecia (com o Sincronizar em Rust também; não era do servidor Python).
//!
//! ## O que o MC põe no arrasto (banco: avid-panel-sdk/arrastar.md, seção macOS — MC 25.12)
//!
//! O Qt publica o MIME `application/x-dnditemdata` como o UTI `com.trolltech.anymime.application--x-dnditemdata`:
//! 16 bytes de cabeçalho e o XML `<mobIDDragObjectList><mobIDDragObject mobID="…"/>`, legível por outro processo já
//! durante o gesto. Os JSON do Windows (`mc-api-asset-list`, com a ESPÉCIE) chegam só como promessa, sem dado. ⇒ vai
//! à página `tipo: "avid"` com `mob_ids`, e a espécie é perguntada ao motor do módulo (`/arrasto/mc`).
//! ⚠️ A janela só recebe o arrasto se REGISTRAR esse UTI.
//! ⛔ O arrasto de SEGMENTOS da timeline do MC não sai do MC no Mac (medido em 25/10): a timeline vem da BIN.
//!
//! ## O que o PREMIERE põe no arrasto da bin (medido em 2026-11-12, Premiere 26.0.2, macOS 15.6.1)
//!
//! Tipos `dyn.ah62…` = `?0=6:3=<nome>` (conforma a `public.data`, nome de pasteboard antigo): `com.adobe<PID>.premiere/
//! projectitem` e `/masterclipvector` (8 bytes, ponteiros) e, quando o arrasto leva SEQUÊNCIAS (uma sequência, ou uma
//! pasta que as contém), `com.adobe.dvaui.dynamiclinksourcelist` — o XML `<LiveLinkSourceList>` com o `.prproj` e o
//! `ObjectUID` de cada sequência (nome FIXO, o mesmo do Windows). ⭐ Registrar `public.data` basta para a janela receber
//! o gesto — sem saber o PID, que muda a cada abertura (medido com a sonda registrada só para ele). Como no Windows:
//! `premiere` (com o XML em `dados`) ou `premiere_item`, e a página lê a SELEÇÃO pela ponte no soltar.
//!
//! ## Diferente do De Lá Pra Cá
//!
//! Aqui a janela tem uma webview filha por módulo: todas registram o tipo, e o aviso vai à função de arrasto da aba
//! VISÍVEL (`sincArrasto`, `cicloArrasto`, `delapracaArrasto`), seja qual for a webview que recebeu (ver `instalar`).
//! ⭐ `x`/`y` em pontos, na página da aba: o `y` do wry vem descontado do rodapé (medido; ver `instalar`).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::{class, msg_send};
use objc2_foundation::{NSArray, NSData, NSString};
use tauri::{DragDropEvent, WebviewEvent};

/// O tipo do arrasto do MC como o Qt o publica (o MIME com "/" → "--").
const UTI_MC: &str = "com.trolltech.anymime.application--x-dnditemdata";
/// `NSPasteboardNameDrag` — o pasteboard do arrasto em curso (e do último, depois de soltar).
const PASTEBOARD_DE_ARRASTO: &str = "Apple CFPasteboard drag";
/// Um tipo que todo `dyn.ah62…` do Premiere conforma (ver o cabeçalho).
const UTI_DADOS: &str = "public.data";
/// A lista de sequências do Premiere (nome fixo, sem PID) e o item da bin (com o PID no meio: pelo sufixo).
const PREMIERE_DL: &str = "com.adobe.dvaui.dynamiclinksourcelist";
const PREMIERE_ITEM_SUFIXO: &str = ".premiere/projectitem";

/// O nome por trás de um UTI dinâmico (`dyn.a` + base32 do `?0=6:3=<nome>`); `None` se não for um.
fn nome_do_dyn(uti: &str) -> Option<String> {
    const ALFABETO: &[u8] = b"abcdefghkmnpqrstuvwxyz0123456789";
    let corpo = uti.strip_prefix("dyn.a")?;
    let (mut acc, mut n, mut bytes) = (0u32, 0u32, Vec::new());
    for c in corpo.bytes() {
        acc = (acc << 5) | ALFABETO.iter().position(|&a| a == c)? as u32;
        n += 5;
        if n >= 8 {
            n -= 8;
            bytes.push((acc >> n) as u8);
            acc &= (1 << n) - 1;
        }
    }
    let texto = String::from_utf8_lossy(&bytes).into_owned();
    Some(texto.rsplit_once(":3=").map(|(_, nome)| nome.to_string()).unwrap_or(texto))
}

/// Os tipos do arrasto em curso, cada um com o nome legível (o `dyn.` decodificado) ao lado.
fn tipos_do_arrasto() -> Vec<(String, String)> {
    unsafe {
        let pb: *mut AnyObject =
            msg_send![class!(NSPasteboard), pasteboardWithName: &*NSString::from_str(PASTEBOARD_DE_ARRASTO)];
        if pb.is_null() {
            return Vec::new();
        }
        let tipos: Option<Retained<NSArray<NSString>>> = msg_send![pb, types];
        tipos
            .map(|a| a.to_vec())
            .unwrap_or_default()
            .iter()
            .map(|t| {
                let uti = t.to_string();
                let nome = nome_do_dyn(&uti).unwrap_or_else(|| uti.clone());
                (uti, nome)
            })
            .collect()
    }
}

/// O texto de um tipo do arrasto em curso (pelo UTI de verdade).
fn texto_do_arrasto(uti: &str) -> String {
    unsafe {
        let pb: *mut AnyObject =
            msg_send![class!(NSPasteboard), pasteboardWithName: &*NSString::from_str(PASTEBOARD_DE_ARRASTO)];
        if pb.is_null() {
            return String::new();
        }
        let d: Option<Retained<NSData>> = msg_send![pb, dataForType: &*NSString::from_str(uti)];
        d.map(|d| String::from_utf8_lossy(&d.to_vec()).into_owned()).unwrap_or_default()
    }
}

/// Do Premiere? `Some((tipo, dados))`: `premiere` com o XML das sequências, ou `premiere_item` sem dado.
fn do_premiere() -> Option<(&'static str, String)> {
    let tipos = tipos_do_arrasto();
    if let Some((uti, _)) = tipos.iter().find(|(_, nome)| nome == PREMIERE_DL) {
        return Some(("premiere", texto_do_arrasto(uti)));
    }
    let item = tipos.iter().any(|(_, n)| n.starts_with("com.adobe") && n.ends_with(PREMIERE_ITEM_SUFIXO));
    item.then(|| ("premiere_item", String::new()))
}

/// Os MobIDs do arrasto do MC em curso, se for um; vazio para qualquer outro arrasto.
fn mob_ids_do_arrasto() -> Vec<String> {
    let dados = unsafe {
        let pb: *mut AnyObject =
            msg_send![class!(NSPasteboard), pasteboardWithName: &*NSString::from_str(PASTEBOARD_DE_ARRASTO)];
        if pb.is_null() {
            return Vec::new();
        }
        let d: Option<Retained<NSData>> = msg_send![pb, dataForType: &*NSString::from_str(UTI_MC)];
        match d {
            Some(d) => d.to_vec(),
            None => return Vec::new(),
        }
    };
    mob_ids_do_xml(&String::from_utf8_lossy(&dados))
}

/// `mobID="…"` de cada `mobIDDragObject`, na ordem, na forma da API (26-6-16-12-4). ⚠️ O XML do MC 25.12 grafa com
/// CHAVES (`060a2b340101010501010f20-13-00-00-00-{7f39f87f-…}`); os 64 hex estão na mesma ordem.
fn mob_ids_do_xml(texto: &str) -> Vec<String> {
    let mut fora: Vec<String> = Vec::new();
    let mut resto = texto;
    while let Some(i) = resto.find("mobID=\"") {
        resto = &resto[i + 7..];
        let Some(f) = resto.find('"') else { break };
        let h: String = resto[..f].chars().filter(|c| c.is_ascii_hexdigit()).collect::<String>().to_lowercase();
        if h.len() == 64 {
            let id = format!("{}-{}-{}-{}-{}", &h[..26], &h[26..32], &h[32..48], &h[48..60], &h[60..]);
            if !fora.contains(&id) {
                fora.push(id);
            }
        }
        resto = &resto[f..];
    }
    fora
}

/// Acrescenta os tipos do MC e do Premiere aos que a webview já aceita (os de arquivo do wry, os do WebKit).
fn registrar_tipos(webview: &tauri::Webview) {
    let _ = webview.with_webview(|w| unsafe {
        let vista = w.inner() as *mut AnyObject;
        if vista.is_null() {
            return;
        }
        let atuais: Option<Retained<NSArray<NSString>>> = msg_send![vista, registeredDraggedTypes];
        let mut tipos: Vec<Retained<NSString>> = atuais.map(|a| a.to_vec()).unwrap_or_default();
        for novo in [UTI_MC, UTI_DADOS] {
            if !tipos.iter().any(|t| t.to_string() == novo) {
                tipos.push(NSString::from_str(novo));
            }
        }
        let lista = NSArray::from_retained_slice(&tipos);
        let _: () = msg_send![vista, registerForDraggedTypes: &*lista];
    });
}

/// O tipo do arrasto em curso (o `Over` não traz caminhos: vale o que o `Enter` trouxe). GLOBAL: o mesmo gesto pode
/// chegar por mais de uma webview (abaixo).
static COM_ARQUIVOS: AtomicBool = AtomicBool::new(false);
static DO_MC: AtomicBool = AtomicBool::new(false);
/// O arrasto do Premiere em curso: o tipo e o XML (lidos no `Enter`).
static DO_PREMIERE: Mutex<Option<(&'static str, String)>> = Mutex::new(None);
/// Quando foi o último soltar entregue — o mesmo soltar chegando por duas webviews vira um só.
static ULTIMO_SOLTAR: Mutex<Option<Instant>> = Mutex::new(None);

/// Liga o repasse numa webview de módulo. Chamar depois de criada, em TODAS as de módulo.
///
/// ⛔⛔ MEDIDO (2026-11-07, macOS 15.6, Tauri 2.12.5): com as webviews dos módulos empilhadas no mesmo lugar e só a da
/// aba visível mostrada, o soltar NÃO chegou à visível (a Preparar) e chegou DUAS vezes pelas escondidas (a do
/// Assistir e a do Entregar). ⇒ quem recebe não importa: o aviso vai à aba VISÍVEL (`modulo_ativo`, o mesmo do
/// `arrasto_win`), e o soltar repetido em menos de 500 ms é descartado.
pub fn instalar(webview: &tauri::Webview) {
    instalar_em(webview, None);
}

/// Liga o repasse numa webview que É o destino (a janela da Carta Aberta): o aviso vai a ela, em `funcao`, e o ponto é
/// o da janela inteira (sem rodapé abaixo da webview).
pub fn instalar_na_janela(webview: &tauri::Webview, funcao: &'static str) {
    // a barra de título = a moldura do NSWindow − a área do conteúdo (`contentLayoutRect`), em pontos
    let _ = webview.with_webview(|w| unsafe {
        let vista = w.inner() as *mut AnyObject;
        if vista.is_null() {
            return;
        }
        let janela: *mut AnyObject = msg_send![vista, window];
        if janela.is_null() {
            return;
        }
        let moldura: objc2_foundation::NSRect = msg_send![janela, frame];
        let conteudo: objc2_foundation::NSRect = msg_send![janela, contentLayoutRect];
        let barra = (moldura.size.height - conteudo.size.height).max(0.0);
        BARRA_DA_CARTA.store(barra.to_bits(), Ordering::Relaxed);
        crate::registro::registrar(&format!("arrasto (mac): barra de título da Carta = {barra} pt"));
    });
    instalar_em(webview, Some((webview.clone(), funcao)));
}

/// A altura da barra de título da janela da Carta (f64 em bits), medida ao instalar.
static BARRA_DA_CARTA: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

fn instalar_em(webview: &tauri::Webview, destino: Option<(tauri::Webview, &'static str)>) {
    registrar_tipos(webview);
    webview.on_webview_event(move |evento| {
        let WebviewEvent::DragDrop(ev) = evento else { return };
        // ⛔ MEDIDO (2026-11-07, escala 1, aba Conformar): soltando em y 490 e 700 da tela, com a webview da aba começando
        // em 218, chegaram 242 e 452 — 30 a MENOS, a altura do RODAPÉ do app. O wry 0.55 vira o eixo pela base da
        // JANELA, não pela da webview filha; x chegou certo (955 − 680 = 275). ⇒ soma-se o que fica abaixo da webview.
        //    ⛔ MEDIDO (2026-11-13, janela da Carta, uma webview só): soltando sobre a pasta em y 335 da tela, com a página
        //    começando em 159 + 28 (a barra de título), chegou y 176 — a posição é da JANELA, barra de título incluída.
        //    O Tauri diz `outer_size == inner_size` (730 e 730) nessa janela: a barra é medida no NSWindow (`instalar_na_janela`).
        let abaixo = if destino.is_some() { -f64::from_bits(BARRA_DA_CARTA.load(Ordering::Relaxed)) } else { crate::ALTURA_DO_RODAPE };
        let pagina = |p: &tauri::PhysicalPosition<f64>| (p.x as i32, (p.y + abaixo) as i32);
        let caminhos =
            |v: &Vec<std::path::PathBuf>| -> Vec<String> { v.iter().map(|p| p.to_string_lossy().into_owned()).collect() };
        let mut ids: Vec<String> = Vec::new();
        let (fase, lista, (x, y)) = match ev {
            DragDropEvent::Enter { paths, position } => {
                COM_ARQUIVOS.store(!paths.is_empty(), Ordering::Relaxed);
                DO_MC.store(paths.is_empty() && !mob_ids_do_arrasto().is_empty(), Ordering::Relaxed);
                let premiere = if paths.is_empty() && !DO_MC.load(Ordering::Relaxed) { do_premiere() } else { None };
                *DO_PREMIERE.lock().unwrap_or_else(|e| e.into_inner()) = premiere;
                ("sobre", caminhos(paths), pagina(position))
            }
            DragDropEvent::Over { position } => ("sobre", Vec::new(), pagina(position)),
            DragDropEvent::Drop { paths, position } => {
                {
                    let mut ultimo = ULTIMO_SOLTAR.lock().unwrap_or_else(|e| e.into_inner());
                    if ultimo.is_some_and(|t| t.elapsed() < Duration::from_millis(500)) {
                        return;
                    }
                    *ultimo = Some(Instant::now());
                }
                if DO_MC.load(Ordering::Relaxed) {
                    ids = mob_ids_do_arrasto();
                }
                ("soltou", caminhos(paths), pagina(position))
            }
            DragDropEvent::Leave => ("saiu", Vec::new(), (0, 0)),
            _ => return,
        };
        let premiere = DO_PREMIERE.lock().unwrap_or_else(|e| e.into_inner()).clone();
        let mut dados = String::new();
        let tipo = if COM_ARQUIVOS.load(Ordering::Relaxed) || !lista.is_empty() {
            "arquivos"
        } else if DO_MC.load(Ordering::Relaxed) {
            "avid"
        } else if let Some((t, d)) = premiere {
            dados = d;
            t
        } else {
            "nada"
        };
        let alvo_e_funcao = match &destino {
            Some((wv, f)) => Some((wv.clone(), *f)),
            None => crate::modulo_ativo().map(|(wv, f, _)| (wv, f)),
        };
        let Some((alvo, funcao)) = alvo_e_funcao else { return };
        if fase == "soltou" {
            crate::registro::registrar(&format!("arrasto (mac): {funcao} {tipo} {} mob(s) em ({x}, {y})", ids.len()));
        }
        let mut v = serde_json::json!({ "fase": fase, "tipo": tipo, "x": x, "y": y, "caminhos": lista, "mob_ids": ids });
        if !dados.is_empty() {
            v["dados"] = serde_json::Value::String(dados);
        }
        let _ = alvo.eval(format!("window.{funcao} && window.{funcao}({v})"));
    });
}

#[cfg(test)]
mod testes {
    use super::{mob_ids_do_xml, nome_do_dyn};

    #[test]
    fn o_dyn_do_premiere() {
        // medidos em 2026-11-12 (Premiere 26.0.2, macOS 15.6.1)
        assert_eq!(nome_do_dyn("dyn.ah62d4rv4gq80g55rf3u0k55cqy1gk7xbszyw63d3r3u044pdrvy0645xr741e25frvy1g7a").as_deref(),
                   Some("com.adobe.dvaui.dynamiclinksourcelist"));
        assert_eq!(nome_do_dyn("dyn.ah62d4rv4gq80g55rf3u0k55cqy2xeq3zgq1ha6xfrzy0n6xff72he55nqzv1k4pyqz0u").as_deref(),
                   Some("com.adobe12353.premiere/projectitem"));
        assert_eq!(nome_do_dyn("public.data"), None);
    }

    #[test]
    fn o_xml_do_mc() {
        let xml_mc = "<mobIDDragObjectList local=\"true\"><mobIDDragObject \
                      mobID=\"060a2b340101010501010f20-13-00-00-00-{7f39f87f-3349-4b9c-a40a3e706d4b2f3a}\" \
                      keyframe=\"0\" /></mobIDDragObjectList>";
        assert_eq!(mob_ids_do_xml(xml_mc),
                   vec!["060a2b340101010501010f2013-000000-7f39f87f33494b9c-a40a3e706d4b-2f3a".to_string()]);
        assert!(mob_ids_do_xml("").is_empty());
    }
}
