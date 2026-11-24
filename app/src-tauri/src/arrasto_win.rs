//! O arrasto na janela do Ciclo Assist — um `IDropTarget` NOSSO no lugar do do WebView2 (Windows).
//!
//! ⭐ Copiado do Sincronizar (`DRAMASYNC/src-tauri/src/arrasto_win.rs`, 2026-10-21), que o copiou do De Lá Pra Cá e acrescentou
//! o item do Premiere pelo SUFIXO.
//!
//! ⭐⭐ No GUARDA-CHUVA (as abas Preparar · Assistir · Conformar · Entregar, 2026-10-21) a janela tem várias webviews
//! filhas, e o arrasto vai para a da ABA VISÍVEL, na função que cada módulo já tem: `cicloArrasto` (Assist),
//! `sincArrasto` (Sincronizar), `delapracaArrasto` (De Lá Pra Cá) — `crate::modulo_ativo()`. Nenhum módulo muda: o
//! aviso é o MESMO formato nos três (eles vêm da mesma cópia).
//!
//! ## Por que (medido em 2026-10-18, MC 24.6, Windows 11, autor)
//!
//! Com o drop da própria webview, dois defeitos:
//! - ⛔ **Soltar uma timeline do MC fez o AVID começar um EXPORT** ("The sequence … contains offline media. Continue
//!   exporting or abort?", modal, que trava até o Explorer). O arrasto de uma sequência anuncia, além da identidade,
//!   um `.aaf` virtual (`CF_HDROP` para um GUID em `%TEMP%`) que o MC só gera quando o alvo PEDE o arquivo — e o
//!   WebView2 pede. Banco: avid-panel-sdk/arrastar.md §4 ("O `.aaf` anexo ao arrasto tem ZERO BYTES").
//! - **A pasta do Explorer chegou sem caminho** (o `File` da web não expõe o caminho).
//!
//! ## O que este alvo faz
//!
//! Pergunta os formatos com `QueryGetData` (não gera dado) e decide:
//! 1. tem `text/x.avid.mc-api-asset-list+json` → é do Avid: no drop lê SÓ ele (os MobIDs). ⛔ Nunca `CF_HDROP` aqui.
//! 2. tem `mediacomposer.sidebar.bins.list` → é a bin do painel lateral, que não traz identidade (banco, §4): avisa.
//! 3. tem `MediaPool/FusionMedia` → uma timeline (ou clipe) do Media Pool do RESOLVE: o `MEDIA_ID` em texto
//!    (banco, resolve-scripting/api-scripting.md §"Arrastar do Media Pool", Resolve 19, 2026-10-12).
//! 4. tem `dynamiclinksourcelist` → uma SEQUÊNCIA do projeto do PREMIERE: XML com o `.prproj` e o `sequenceID`
//!    (banco, premiere-cep/arrastar-e-selecao.md §6b, 23.2). Item do Premiere SEM ele (um clipe) = `premiere_item`.
//! 5. tem `CF_HDROP` → caminhos do Explorer.
//!
//! Os do Resolve e do Premiere são lidos já no `DragEnter`: são texto pequeno, não fazem a origem gerar arquivo nenhum
//! (o perigo do Avid é o `.aaf` virtual), e o Premiere deixa o cursor BLOQUEADO sobre a janela (banco, §6b) — o soltar
//! pode nem chegar. A página recebe o dado em todo "sobre" e decide.
//!
//! E entrega à página por `eval` (`window.cicloArrasto({fase, tipo, x, y, …})`), que monta o MESMO
//! `dataTransfer` que o painel sempre leu. Sem IPC para a origem HTTP — a página não ganha canal novo nenhum.
//!
//! O registro é o do wry (`webview2/drag_drop.rs`): `SetAllowExternalDrop(false)` e `RegisterDragDrop` na janela e
//! nas filhas do nosso processo. Fora isso, o tratador do Tauri fica DESLIGADO (`disable_drag_drop_handler`): o dele
//! lê o `CF_HDROP` já na entrada, que é exatamente o que dispara o export.

use std::cell::{Cell, RefCell};
use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;

use windows::core::{implement, Interface, Ref, BOOL, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, POINT, POINTL};
use windows::Win32::Graphics::Gdi::ScreenToClient;
use windows::Win32::System::Com::{IDataObject, DATADIR_GET, DVASPECT_CONTENT, FORMATETC, TYMED_HGLOBAL};
use windows::Win32::System::DataExchange::{GetClipboardFormatNameW, RegisterClipboardFormatW};
use windows::Win32::System::Memory::{GlobalLock, GlobalSize, GlobalUnlock};
use windows::Win32::System::Ole::{
    IDropTarget, IDropTarget_Impl, RegisterDragDrop, ReleaseStgMedium, RevokeDragDrop, CF_HDROP, DROPEFFECT,
    DROPEFFECT_COPY, DROPEFFECT_LINK, DROPEFFECT_MOVE, DROPEFFECT_NONE,
};
use windows::Win32::System::SystemServices::MODIFIERKEYS_FLAGS;
use windows::Win32::UI::Shell::{DragQueryFileW, HDROP};
use windows::Win32::UI::WindowsAndMessaging::EnumChildWindows;

const MIME_AVID: &str = "text/x.avid.mc-api-asset-list+json";
const MIME_BIN: &str = "mediacomposer.sidebar.bins.list";
const RESOLVE_ID: &str = "MediaPool/FusionMedia";
const RESOLVE_PROPS: &str = "MediaPool/FusionMediaProperties";
const PREMIERE_DL: &str = "dynamiclinksourcelist";
/// ⛔ O formato do item do Premiere NÃO tem nome fixo: é `Adobe<número>/Premiere/ProjectItem`, e o número muda
/// (o banco mediu `Adobe34116` no 23.2; no 23.6 de 2026-10-21 o nome fixo não casou e o arrasto de um clipe chegou
/// como "nada"). Reconhecer pelo SUFIXO, olhando os formatos que o arrasto oferece.
const PREMIERE_ITEM_SUFIXO: &str = "/Premiere/ProjectItem";

#[derive(Clone, Copy, PartialEq)]
enum Tipo {
    Nada,
    Avid,
    Bin,
    Resolve,
    Premiere,
    PremiereItem,
    Arquivos,
}

impl Tipo {
    fn nome(self) -> &'static str {
        match self {
            Tipo::Nada => "nada",
            Tipo::Avid => "avid",
            Tipo::Bin => "bin",
            Tipo::Resolve => "resolve",
            Tipo::Premiere => "premiere",
            Tipo::PremiereItem => "premiere_item",
            Tipo::Arquivos => "arquivos",
        }
    }
}

/// O número do formato registrado com este nome. O Qt registra os MIME próprios do Avid no OLE pelo próprio nome
/// (a sonda nativa do banco listou `text/x.avid.asset-list-extended+json`, `application/x-dnditemdata`…).
fn formato(nome: &str) -> u16 {
    let largo: Vec<u16> = nome.encode_utf16().chain(Some(0)).collect();
    unsafe { RegisterClipboardFormatW(PCWSTR(largo.as_ptr())) as u16 }
}

fn pedido(cf: u16) -> FORMATETC {
    FORMATETC {
        cfFormat: cf,
        ptd: std::ptr::null_mut(),
        dwAspect: DVASPECT_CONTENT.0,
        lindex: -1,
        tymed: TYMED_HGLOBAL.0 as u32,
    }
}

/// Oferece o formato? `QueryGetData` só pergunta — não faz a origem gerar nada.
fn oferece(obj: &IDataObject, cf: u16) -> bool {
    unsafe { obj.QueryGetData(&pedido(cf)) }.0 == 0
}

fn tipo_de(obj: &IDataObject) -> Tipo {
    // ⚠️ NESTA ORDEM: o arrasto do Avid TAMBÉM oferece `CF_HDROP` (o `.aaf`/`.mxf` virtual).
    if oferece(obj, formato(MIME_AVID)) {
        Tipo::Avid
    } else if oferece(obj, formato(MIME_BIN)) {
        Tipo::Bin
    } else if oferece(obj, formato(RESOLVE_ID)) {
        Tipo::Resolve
    } else if oferece(obj, formato(PREMIERE_DL)) {
        Tipo::Premiere
    } else if nomes_dos_formatos(obj).iter().any(|n| n.ends_with(PREMIERE_ITEM_SUFIXO)) {
        Tipo::PremiereItem
    } else if oferece(obj, CF_HDROP.0) {
        Tipo::Arquivos
    } else {
        Tipo::Nada
    }
}

/// Os nomes dos formatos REGISTRADOS que o arrasto oferece (os números < 0xC000 são os do sistema, sem nome).
fn nomes_dos_formatos(obj: &IDataObject) -> Vec<String> {
    let mut nomes = Vec::new();
    unsafe {
        let Ok(lista) = obj.EnumFormatEtc(DATADIR_GET.0 as u32) else { return nomes };
        loop {
            let mut f = [FORMATETC::default()];
            let mut lidos = 0u32;
            if lista.Next(&mut f, Some(&mut lidos)).is_err() || lidos == 0 {
                break;
            }
            let mut buf = [0u16; 256];
            let n = GetClipboardFormatNameW(f[0].cfFormat as u32, &mut buf);
            if n > 0 {
                nomes.push(String::from_utf16_lossy(&buf[..n as usize]));
            }
        }
    }
    nomes
}

/// Os bytes de um formato `HGLOBAL`, sem o zero final.
fn ler_bytes(obj: &IDataObject, cf: u16) -> Option<Vec<u8>> {
    unsafe {
        let mut meio = obj.GetData(&pedido(cf)).ok()?;
        let h = meio.u.hGlobal;
        let p = GlobalLock(h);
        let bytes = if p.is_null() {
            None
        } else {
            let v = std::slice::from_raw_parts(p as *const u8, GlobalSize(h)).to_vec();
            let _ = GlobalUnlock(h);
            Some(v)
        };
        ReleaseStgMedium(&mut meio);
        bytes.map(|mut v| {
            while v.last() == Some(&0) {
                v.pop();
            }
            v
        })
    }
}

fn texto(obj: &IDataObject, nome: &str) -> String {
    ler_bytes(obj, formato(nome)).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default()
}

/// O que se lê já na entrada: a identidade do Resolve (o `MEDIA_ID` + as propriedades em hexadecimal, um QDataStream
/// UTF-16BE que o serviço decodifica) ou o XML do Premiere.
fn identidade(obj: &IDataObject, tipo: Tipo) -> serde_json::Value {
    match tipo {
        Tipo::Resolve => {
            let props = ler_bytes(obj, formato(RESOLVE_PROPS)).unwrap_or_default();
            let hex: String = props.iter().take(8192).map(|b| format!("{b:02x}")).collect();
            serde_json::json!({ "media_id": texto(obj, RESOLVE_ID).trim(), "props": hex })
        }
        Tipo::Premiere => serde_json::json!({ "dados": texto(obj, PREMIERE_DL) }),
        _ => serde_json::json!({}),
    }
}

fn ler_caminhos(obj: &IDataObject) -> Vec<String> {
    let mut saida = Vec::new();
    unsafe {
        let Ok(mut meio) = obj.GetData(&pedido(CF_HDROP.0)) else { return saida };
        let hdrop = HDROP(meio.u.hGlobal.0 as _);
        for i in 0..DragQueryFileW(hdrop, u32::MAX, None) {
            let n = DragQueryFileW(hdrop, i, None) as usize;
            let mut buf = vec![0u16; n + 1];
            DragQueryFileW(hdrop, i, Some(&mut buf));
            saida.push(OsString::from_wide(&buf[..n]).to_string_lossy().into_owned());
        }
        ReleaseStgMedium(&mut meio);
    }
    saida
}

/// O efeito que a ORIGEM permite. ⚠️ O MC arrasta com "move" e cancela calado um efeito fora do que permitiu
/// (banco, arrastar.md §5) — o "move" dele é rótulo, nada sai do projeto.
fn efeito_permitido(permitidos: DROPEFFECT) -> DROPEFFECT {
    for e in [DROPEFFECT_COPY, DROPEFFECT_LINK, DROPEFFECT_MOVE] {
        if permitidos.0 & e.0 != 0 {
            return e;
        }
    }
    DROPEFFECT_NONE
}

#[implement(IDropTarget)]
struct Alvo {
    janela: tauri::Window,
    topo: isize,
    tipo: Cell<Tipo>,
    efeito: Cell<DROPEFFECT>,
    ponto: Cell<(i32, i32)>,
    /// A identidade lida no `DragEnter` (Resolve, Premiere); vai em todo aviso deste arrasto.
    lido: RefCell<serde_json::Value>,
    /// A webview que recebe e a função dela (a janela da Carta Aberta); `None` = a aba visível da janela principal.
    destino: Option<(tauri::Webview, &'static str)>,
}

impl Alvo {
    /// Tela → página (pixels CSS): a webview ocupa a área cliente inteira da janela.
    fn na_pagina(&self, pt: &POINTL) -> (i32, i32) {
        let mut p = POINT { x: pt.x, y: pt.y };
        unsafe {
            let _ = ScreenToClient(HWND(self.topo as _), &mut p);
        }
        let escala = self.janela.scale_factor().unwrap_or(1.0);
        // a webview do módulo começa ABAIXO da barra de abas: o ponto é dela, não da janela
        let topo_da_aba = if self.destino.is_some() { 0.0 } else { crate::modulo_ativo().map(|(_, _, y)| y).unwrap_or(0.0) };
        ((p.x as f64 / escala) as i32, (p.y as f64 / escala - topo_da_aba) as i32)
    }

    fn avisar(&self, fase: &str, (x, y): (i32, i32), extra: serde_json::Value) {
        if fase != "sobre" {
            eprintln!("[CicloAssist] arrasto: {fase} {}", self.tipo.get().nome());
        }
        let mut v = serde_json::json!({ "fase": fase, "tipo": self.tipo.get().nome(), "x": x, "y": y });
        if let (Some(m), serde_json::Value::Object(e)) = (v.as_object_mut(), self.lido.borrow().clone()) {
            m.extend(e);
        }
        if let (Some(m), serde_json::Value::Object(e)) = (v.as_object_mut(), extra) {
            m.extend(e);
        }
        let alvo = match &self.destino {
            Some((wv, f)) => Some((wv.clone(), *f)),
            None => crate::modulo_ativo().map(|(wv, f, _)| (wv, f)),
        };
        if let Some((webview, funcao)) = alvo {
            let _ = webview.eval(format!("window.{funcao} && window.{funcao}({v})"));
        }
    }

    fn efeito_de(&self, permitidos: DROPEFFECT) -> DROPEFFECT {
        match self.tipo.get() {
            Tipo::Nada => DROPEFFECT_NONE,
            _ => efeito_permitido(permitidos),
        }
    }
}

#[allow(non_snake_case)]
impl IDropTarget_Impl for Alvo_Impl {
    fn DragEnter(
        &self,
        obj: Ref<'_, IDataObject>,
        _teclas: MODIFIERKEYS_FLAGS,
        pt: &POINTL,
        efeito: *mut DROPEFFECT,
    ) -> windows::core::Result<()> {
        let tipo = obj.as_ref().map(tipo_de).unwrap_or(Tipo::Nada);
        if let Some(o) = obj.as_ref() {
            // uma linha por arrasto: é o que diz, sem depurador, por que um arrasto chegou como "nada"
            eprintln!("[CicloAssist] arrasto: formatos {:?}", nomes_dos_formatos(o));
        }
        self.tipo.set(tipo);
        *self.lido.borrow_mut() = obj.as_ref().map(|o| identidade(o, tipo)).unwrap_or(serde_json::json!({}));
        let p = self.na_pagina(pt);
        self.ponto.set(p);
        unsafe {
            let e = self.efeito_de(*efeito);
            self.efeito.set(e);
            *efeito = e;
        }
        self.avisar("sobre", p, serde_json::json!({}));
        Ok(())
    }

    fn DragOver(&self, _teclas: MODIFIERKEYS_FLAGS, pt: &POINTL, efeito: *mut DROPEFFECT) -> windows::core::Result<()> {
        let p = self.na_pagina(pt);
        if p != self.ponto.get() {
            self.ponto.set(p);
            self.avisar("sobre", p, serde_json::json!({}));
        }
        unsafe {
            *efeito = self.efeito.get();
        }
        Ok(())
    }

    fn DragLeave(&self) -> windows::core::Result<()> {
        self.avisar("saiu", self.ponto.get(), serde_json::json!({}));
        Ok(())
    }

    fn Drop(
        &self,
        obj: Ref<'_, IDataObject>,
        _teclas: MODIFIERKEYS_FLAGS,
        pt: &POINTL,
        efeito: *mut DROPEFFECT,
    ) -> windows::core::Result<()> {
        let p = self.na_pagina(pt);
        let extra = match (self.tipo.get(), obj.as_ref()) {
            (Tipo::Avid, Some(o)) => {
                let texto = ler_bytes(o, formato(MIME_AVID))
                    .map(|b| String::from_utf8_lossy(&b).into_owned())
                    .unwrap_or_default();
                serde_json::json!({ "dados": texto })
            }
            (Tipo::Arquivos, Some(o)) => serde_json::json!({ "caminhos": ler_caminhos(o) }),
            _ => serde_json::json!({}),
        };
        self.avisar("soltou", p, extra);
        unsafe {
            *efeito = self.efeito.get();
        }
        Ok(())
    }
}

/// Liga o alvo na janela e em TODAS as webviews dela. Chamar depois de criar as webviews, de qualquer thread: o
/// registro roda na thread da interface (`with_webview`), que é a que tem o OLE iniciado. ⚠️ Webview criada DEPOIS
/// não ganha o alvo: cada uma traz o do WebView2, que pede o arquivo do arrasto (o export de AAF do MC).
pub fn instalar(janela: &tauri::Window, webviews: &[tauri::Webview]) {
    instalar_com_destino(janela, webviews, None);
}

/// O mesmo, numa janela cuja webview É o destino (a Carta Aberta): o aviso vai a ela, em `funcao`.
pub fn instalar_na_janela(janela: &tauri::Window, webview: &tauri::Webview, funcao: &'static str) {
    instalar_com_destino(janela, std::slice::from_ref(webview), Some((webview.clone(), funcao)));
}

fn instalar_com_destino(janela: &tauri::Window, webviews: &[tauri::Webview], destino: Option<(tauri::Webview, &'static str)>) {
    let Ok(topo) = janela.hwnd() else { return };
    let topo = topo.0 as isize;
    for (i, wv) in webviews.iter().enumerate() {
        let ultima = i + 1 == webviews.len();
        let j = janela.clone();
        let destino = destino.clone();
        let _ = wv.with_webview(move |pw| unsafe {
            use webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Controller4;
            if let Ok(c) = pw.controller().cast::<ICoreWebView2Controller4>() {
                let _ = c.SetAllowExternalDrop(false);
            }
            if ultima {
                registrar_em_tudo(&j, topo, destino);
            }
        });
    }
}

unsafe fn registrar_em_tudo(j: &tauri::Window, topo: isize, destino: Option<(tauri::Webview, &'static str)>) {
    let registrar = |hwnd: HWND| {
        let alvo: IDropTarget = Alvo {
            janela: j.clone(),
            topo,
            tipo: Cell::new(Tipo::Nada),
            efeito: Cell::new(DROPEFFECT_NONE),
            ponto: Cell::new((0, 0)),
            lido: RefCell::new(serde_json::json!({})),
            destino: destino.clone(),
        }
        .into();
        let _ = RevokeDragDrop(hwnd);
        // ⚠️ O OLE guarda a sua própria referência; a nossa pode sair de escopo.
        if let Err(e) = RegisterDragDrop(hwnd, &alvo) {
            eprintln!("[CicloAssist] arrasto: alvo em {:#x} recusado: {e}", hwnd.0 as isize);
        }
    };
    registrar(HWND(topo as _));
    let mut cb = |h: HWND| registrar(h);
    let mut obj: &mut dyn FnMut(HWND) = &mut cb;
    unsafe extern "system" fn cada(h: HWND, l: LPARAM) -> BOOL {
        let f = &mut *(l.0 as *mut &mut dyn FnMut(HWND));
        f(h);
        true.into()
    }
    let _ = EnumChildWindows(Some(HWND(topo as _)), Some(cada), LPARAM(&mut obj as *mut _ as isize));
}
