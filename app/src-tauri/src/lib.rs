//! Ciclo Assist — o GUARDA-CHUVA: uma janela, quatro abas, cada aba um app.
//!
//! ⭐⭐ O desenho do autor (2026-10-21, `docs/plano/2026-10-21-assist-standalone.md`): **Preparar** (Sincronizar) ·
//! **Assistir** (o chat, o único módulo exclusivo do Assist) · **Conformar** (De Lá Pra Cá) · **Entregar** (Promo
//! Entrega, em breve). Cada módulo é desenvolvido no app dele; aqui ele aparece no estado em que está.
//!
//! ⭐ Fase de COMPOSIÇÃO (decisão do autor, 2026-10-21): cada aba é uma webview filha que mostra a página do painel do
//! módulo, servida pelo MOTOR dele, subido a partir da pasta do app — o Assist (7824), o De Lá Pra Cá (7823) e o
//! Sincronizar (7817, o ex-Sincronizar, em Python desde 2026-11-07 — `modulos/sincronizar/servidor`). A cópia importada de
//! cada módulo vem na fase de unificação.
//!
//! Trocar de aba esconde e mostra webviews: nada recarrega, e a conversa e o trabalho de cada módulo seguem vivos.
//!
//! ⛔ As páginas dos módulos são REMOTAS (HTTP) e não têm ponte com o Rust — de propósito: mostram texto que um modelo
//! escreveu. Quando pedem algo à janela (o pino, fechar, alargar), o motor reinvoca este executável com um argumento
//! e o `single_instance` entrega a esta instância. Só a barra de abas (local, `ui/abas.html`) fala com o Rust.
//!
//! ⚠️⚠️ `withGlobalTauri: true` no `tauri.conf.json` é OBRIGATÓRIO para as páginas locais: sem ele não há
//! `window.__TAURI__`, e a barra de abas fica muda.

mod ajustes;
#[cfg(target_os = "macos")]
mod arrasto_mac;
#[cfg(windows)]
mod arrasto_win;
mod carta;
mod oficina;
mod registro;
mod supervisor;
use registro::registrar;

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{LogicalPosition, LogicalSize, Manager, WebviewUrl};

const JANELA: &str = "main";
/// A moldura do guarda-chuva (autor, 2026-10-21): UMA para os quatro apps. Em cima, o estado da conexão com o NLE e o
/// pino; embaixo dele, as abas e a engrenagem única. No pé, a assinatura. Os apps, embutidos (`?embutido=1`), escondem
/// a moldura deles.
const TOPO: &str = "topo";
const RODAPE: &str = "rodape";

/// As alturas da moldura, em pixels lógicos — as mesmas do `ui/topo.css` e do `ui/rodape.css`.
const ALTURA_DO_TOPO: f64 = 76.0;
pub(crate) const ALTURA_DO_RODAPE: f64 = 30.0;

/// O perfil do autor (o link da assinatura). Fixo no binário: não há comando que aceite URL.
const AUTOR_URL: &str = "https://www.linkedin.com/in/lohan-costa/";

/// O tamanho no 1º uso: no MEIO da tela (autor, 2026-11-07). Os painéis dos módulos foram desenhados para
/// ~400–480 px; 560 dá folga a eles. ⭐ Autor (2026-11-07): "meio alto, parece que tenta ocupar toda a altura" — era
/// 480 × a altura útil inteira; hoje a altura vai até `ALTURA` e nunca passa de `FRACAO_DA_ALTURA` da tela.
const LARGURA: f64 = 560.0;
const ALTURA: f64 = 820.0;
const FRACAO_DA_ALTURA: f64 = 0.85;

/// A largura da revisão de mídias do De Lá Pra Cá (`--janela-larga`): os dois nomes de arquivo lado a lado.
const LARGURA_LARGA: f64 = 1180.0;

/// Os módulos, na ordem das abas.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Serialize)]
#[serde(rename_all = "lowercase")]
enum Modulo {
    Preparar,
    Assistir,
    Conformar,
    Entregar,
}

impl Modulo {
    const TODOS: [Modulo; 4] = [Modulo::Preparar, Modulo::Assistir, Modulo::Conformar, Modulo::Entregar];

    fn rotulo(self) -> &'static str {
        match self {
            Modulo::Preparar => "preparar",
            Modulo::Assistir => "assistir",
            Modulo::Conformar => "conformar",
            Modulo::Entregar => "entregar",
        }
    }

    fn de(nome: &str) -> Option<Modulo> {
        Modulo::TODOS.into_iter().find(|m| m.rotulo() == nome)
    }

    /// A porta do motor e o caminho do painel dele. `None` = ainda não há motor (Entregar).
    fn motor(self) -> Option<(u16, &'static str)> {
        match self {
            Modulo::Preparar => Some((7817, "/avid/panel?casca=app&embutido=1")),
            Modulo::Assistir => Some((7824, "/painel?casca=app&embutido=1")),
            Modulo::Conformar => Some((7823, "/painel?nle=mc&casca=app&embutido=1")),
            Modulo::Entregar => None,
        }
    }

    /// Como o editor chama o motor (o topo e a aba usam no aviso).
    fn nome_do_motor(self) -> &'static str {
        match self {
            Modulo::Preparar => "o Sincronizar",
            Modulo::Assistir => "o serviço do Assist",
            Modulo::Conformar => "o De Lá Pra Cá",
            Modulo::Entregar => "o Promo Entrega",
        }
    }

    /// A função que a página do módulo expõe para receber o arrasto nativo (`arrasto_win`).
    fn funcao_do_arrasto(self) -> &'static str {
        match self {
            Modulo::Preparar => "sincArrasto",
            Modulo::Assistir => "cicloArrasto",
            Modulo::Conformar => "delapracaArrasto",
            Modulo::Entregar => "cicloArrasto",
        }
    }
}

/// Os motores que ESTE app subiu (os que já estavam de pé não são nossos e não são encerrados).
#[derive(Default)]
struct Motores(Mutex<Vec<(Modulo, Child)>>);

/// A aba visível e a geometria da janela (pixels físicos) para o `app.json`.
#[derive(Default)]
struct Estado {
    aba: Option<Modulo>,
    geom: Option<Geometria>,
    antes_de_alargar: Option<Geometria>,
    fixada: bool,
}

#[derive(Default)]
struct EstadoApp(Mutex<Estado>);

/// O app, para o `arrasto_win` achar a aba visível (o alvo OLE não recebe estado do Tauri). Vazio antes do `setup`.
static APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

/// A webview do módulo da aba visível, a função de arrasto dela e onde ela começa (y lógico).
pub(crate) fn modulo_ativo() -> Option<(tauri::Webview, &'static str, f64)> {
    let app = APP.get()?;
    let aba = app.state::<EstadoApp>().0.lock().ok()?.aba?;
    let wv = app.get_webview(aba.rotulo())?;
    Some((wv, aba.funcao_do_arrasto(), ALTURA_DO_TOPO))
}

fn porta_ocupada(porta: u16) -> bool {
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};
    use std::time::Duration;
    let alvo = SocketAddr::from((Ipv4Addr::LOCALHOST, porta));
    TcpStream::connect_timeout(&alvo, Duration::from_millis(250)).is_ok()
}

// ── onde mora cada módulo ─────────────────────────────────────────────────────

/// A pasta onde os apps da família moram (`2 ATIVOS/`): sobe a partir do executável e, em desenvolvimento, de onde o
/// app foi compilado, até achar a pasta que tem o Assist (`_CICLO ASSIST`) — o `target/` mora fora do SSD.
/// ⚠️ Nunca um caminho fixo: a regra da família manda achar SUBINDO (o SSD muda de letra e de sistema).
fn pasta_dos_apps() -> Option<PathBuf> {
    let mut inicios = vec![];
    if let Ok(exe) = std::env::current_exe() {
        inicios.push(exe.parent()?.to_path_buf());
    }
    if cfg!(debug_assertions) {
        inicios.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    }
    for inicio in inicios {
        let mut d = inicio;
        for _ in 0..8 {
            if d.join("cicloassist/servico/__main__.py").is_file() {
                return d.parent().map(Path::to_path_buf);
            }
            match d.parent() {
                Some(p) => d = p.to_path_buf(),
                None => break,
            }
        }
    }
    None
}

fn python_do(raiz: &Path) -> PathBuf {
    if cfg!(windows) {
        raiz.join(".venv-win/Scripts/python.exe")
    } else {
        raiz.join(".venv/bin/python")
    }
}

/// O Python do módulo Sincronizar: `SINCRONIZAR_PYTHON`, senão a venv DO MÓDULO (`modulos/sincronizar/.venv` ·
/// `.venv-win`, como a do Conformar; até 2026-11-07 era a do Órbita, fora do SSD). ⚠️ Não é a `.venv` do Assist:
/// falta a ela `scipy` e `zstandard`, e o lock só se gera no Windows (`tools/lock.py`). Uma venv só é da fase 5.
fn python_do_sincronizar() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("SINCRONIZAR_PYTHON").map(PathBuf::from) {
        return p.is_file().then_some(p);
    }
    let py = python_do(&pasta_dos_apps()?.join("_CICLO ASSIST").join("modulos").join("sincronizar"));
    py.is_file().then_some(py)
}

/// O comando que sobe o motor do módulo: (programa, argumentos, pasta de trabalho). `None` = não achei.
///
/// ⚠️ Os motores Python recebem `--app` (este executável) e `--pai` (este PID): reinvocam o app para mexer na janela
/// e encerram quando ele some — no Windows o `kill` atinge o LANÇADOR do venv, não o Python que ele abre (matriz de
/// plataforma, "processo órfão"). O Sincronizar recebe só o `--pai` (`vigia_pai.rs` de lá): o `kill` do fechamento o
/// alcança, mas morto à força este app não mata ninguém, e o órfão segurava a 7817.
fn comando_do_motor(m: Modulo) -> Option<(PathBuf, Vec<String>, PathBuf)> {
    let apps = pasta_dos_apps()?;
    let eu = std::env::current_exe().ok()?.to_string_lossy().into_owned();
    let pai = std::process::id().to_string();
    match m {
        Modulo::Assistir => {
            let raiz = apps.join("_CICLO ASSIST");
            let py = python_do(&raiz);
            py.is_file().then(|| {
                (py, vec!["-m".into(), "cicloassist.servico".into(), "--app".into(), eu, "--pai".into(), pai], raiz)
            })
        }
        Modulo::Conformar => {
            // ⭐ Fase 2 do plano um app só (2026-11-07): o De Lá Pra Cá é o módulo `modulos/conformar` deste repo
            // (com o histórico, `git subtree`); a venv é a dele (`modulos/conformar/.venv` · `.venv-win`).
            let raiz = apps.join("_CICLO ASSIST").join("modulos").join("conformar");
            let servico = raiz.join("plugins/media-composer/servico/main.py");
            let py = python_do(&raiz);
            (py.is_file() && servico.is_file()).then(|| {
                let args = vec![servico.to_string_lossy().into_owned(), "--app".into(), eu, "--pai".into(), pai];
                (py, args, raiz)
            })
        }
        Modulo::Preparar => {
            // ⭐ O servidor do módulo Sincronizar em PYTHON (`modulos/sincronizar/servidor/servidor.py`, o motor no mesmo
            // processo). ⛔ O ex-Órbita em Rust (`--motor`, com `cargo`) foi APOSENTADO em
            // 2026-11-07, com a fase 1 do plano um app só provada (P6 no Premiere e o sync do MC iguais aos do Rust):
            // sem o Python do módulo, a Preparar não sobe e o supervisor diz por quê — nunca um motor velho calado.
            let raiz = apps.join("_CICLO ASSIST");
            let servidor = raiz.join("modulos/sincronizar/servidor/servidor.py");
            let py = python_do_sincronizar()?;
            servidor.is_file().then(|| (py, vec![servidor.to_string_lossy().into_owned(), "--pai".into(), pai], raiz))
        }
        Modulo::Entregar => None,
    }
}

fn sem_janela(cmd: &mut Command) {
    // ⚠️ Sem isto o Windows abre um console preto atrás da janela, e os motores vivem horas.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let _ = cmd;
}

/// Sobe o motor do módulo — a menos que a porta já atenda (o app standalone aberto, ou a bancada): aí ele é usado
/// como está, e não é nosso para encerrar.
/// `religado`: o supervisor está religando um motor que caiu (não é o app abrindo). ⭐ O motor recebe
/// `CICLOASSIST_RELIGADO=1` e o serviço do Assist RETOMA a conversa em vez de começar do zero (2026-11-04: o serviço
/// caiu no meio de um turno e a conversa do editor sumiu junto — e cair não é gesto dele).
fn subir_motor(app: &tauri::AppHandle, m: Modulo, religado: bool) -> Result<(), String> {
    let Some((porta, _)) = m.motor() else { return Ok(()) };
    if porta_ocupada(porta) {
        // ⚠️ Dito no log (2026-11-07): era aqui que o supervisor "adotava" o motor de um app anterior morto à força —
        //    ele se encerra sozinho segundos depois (o `--pai` dele), e a aba ficava 15–90 s fora do ar.
        registrar(&format!("motor de {}: a porta {porta} já atende — uso o que está lá (não foi subido por este app)",
                           m.rotulo()));
        return Ok(());
    }
    let (prog, args, cwd) = comando_do_motor(m).ok_or_else(|| format!("não achei o motor de {}", m.rotulo()))?;
    let mut cmd = Command::new(&prog);
    // ⭐ Fase 4: "você roda como módulo do Ciclo Assist" — o De Lá Pra Cá recusa instalar as integrações DELE (o
    // instalador é o único, `cicloassist/integracoes.py`); rodando sozinho (os testes dele), nada muda.
    cmd.env("CICLOASSIST_MODULO", "1");
    // ⛔⛔ Os fork handlers do gRPC prendiam o motor inteiro ~62 s a cada subprocesso aberto com canais ao MC em uso (o
    //    GIL preso no fork; medido 2026-11-07, eram os "parou de responder… processo vivo" do Conformar). Cada motor já
    //    o desliga antes de importar o gRPC; aqui vale também para quem esquecer.
    cmd.env("GRPC_ENABLE_FORK_SUPPORT", "0");
    cmd.args(args).current_dir(cwd);
    if religado {
        cmd.env("CICLOASSIST_RELIGADO", "1");
    }
    // ⛔ Onde o motor avisa que vai ficar mudo de propósito (`supervisor::TETO_OCUPADO`); o de uma vida anterior sai.
    if let Some(aviso) = arquivo_ocupado(m) {
        let _ = std::fs::remove_file(&aviso);
        cmd.env("CICLOASSIST_OCUPADO", aviso);
    }
    sem_janela(&mut cmd);
    let filho = cmd.spawn().map_err(|e| format!("não consegui subir {}: {e}", prog.display()))?;
    registrar(&format!("motor de {} subido (pid {})", m.rotulo(), filho.id()));
    app.state::<Motores>().0.lock().unwrap().push((m, filho));
    Ok(())
}

/// O motor que atendia a porta de `m` saiu? `Some(como)` se saiu; `None` se o filho DESTE app segue vivo.
///
/// ⛔ Sem filho nosso registrado, a porta muda é `Some`: quem atendia era um motor ADOTADO (`subir_motor` achou a porta
///    ocupada — o de um app anterior, morto à força, que se encerra pelo `--pai` dele). Antes isto era `None`, lido
///    como "o processo continua vivo": esperava 15 s (no ar) ou 90 s (subindo) por um processo que nem existia, e o
///    log afirmava um processo vivo. MEDIDO no app.log de 06–07/11: 5 de 5 "o Conformar parou de responder" vieram
///    logo depois de abrir o app com o anterior morto sem encerrar os motores.
fn filho_saiu(app: &tauri::AppHandle, m: Modulo) -> Option<String> {
    let st = app.state::<Motores>();
    let mut lista = st.0.lock().unwrap();
    let Some((_, filho)) = lista.iter_mut().find(|(x, _)| *x == m) else {
        return Some("o motor que estava na porta não era deste app".into());
    };
    match filho.try_wait() {
        Ok(Some(s)) => Some(s.code().map_or("sem código".into(), |c| format!("código {c}"))),
        _ => None,
    }
}

/// Antes de matar um motor VIVO que não atende a porta: o que o sistema diz da porta e do processo, num arquivo ao
/// lado do `app.log` (`logs/diagnostico-<módulo>-<hora>.txt`). ⭐ 2026-11-07: três "parou de responder" do Conformar
/// com o filho nosso vivo e sem uma linha no log dele — e ao religar a prova sumia. A fila de conexões da porta diz se
/// ele parou de ACEITAR (fila cheia: uma thread segurando o GIL) ou se a porta nem escuta; a pilha diz onde estava.
pub(crate) fn diagnosticar(app: &tauri::AppHandle, m: Modulo) {
    let Some((porta, _)) = m.motor() else { return };
    let pid = app.state::<Motores>().0.lock().unwrap().iter().find(|(x, _)| *x == m).map(|(_, f)| f.id());
    let Some(pasta) = pasta_dados().map(|p| p.join("logs")) else { return };
    let quando = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let destino = pasta.join(format!("diagnostico-{}-{quando}.txt", m.rotulo()));
    let mut corpo = format!("motor de {} · porta {porta} · pid {pid:?}\n", m.rotulo());
    let mut rodar = |titulo: &str, prog: &str, args: &[&str]| {
        let mut cmd = Command::new(prog);
        cmd.args(args);
        sem_janela(&mut cmd);
        let saida = cmd.output().map(|o| String::from_utf8_lossy(&o.stdout).into_owned()).unwrap_or_else(|e| e.to_string());
        let alvo = format!(".{porta}");
        let alvo_win = format!(":{porta}");
        let linhas: String = if titulo.starts_with("pilha") {
            saida
        } else {
            saida.lines().filter(|l| l.contains(&alvo) || l.contains(&alvo_win) || l.contains("Proto") || l.contains("Listen"))
                .map(|l| format!("{l}\n")).collect()
        };
        corpo.push_str(&format!("\n── {titulo} ──\n{linhas}"));
    };
    if cfg!(windows) {
        rodar("conexões", "netstat", &["-ano", "-p", "TCP"]);
    } else {
        rodar("fila de escuta (qlen/incqlen/maxqlen)", "netstat", &["-Lan", "-p", "tcp"]);
        rodar("conexões", "netstat", &["-an", "-p", "tcp"]);
        if let Some(p) = pid {
            rodar("pilha (sample 2 s)", "sample", &[&p.to_string(), "2"]);
        }
    }
    if std::fs::write(&destino, corpo).is_ok() {
        registrar(&format!("motor de {}: diagnóstico em {}", m.rotulo(), destino.display()));
    }
}

/// Mata (e esquece) o motor que ESTE app subiu para `m` — antes de religar.
fn matar_filho(app: &tauri::AppHandle, m: Modulo) {
    let st = app.state::<Motores>();
    let mut lista = st.0.lock().unwrap();
    if let Some(i) = lista.iter().position(|(x, _)| *x == m) {
        let (_, mut filho) = lista.remove(i);
        let _ = filho.kill();
        let _ = filho.wait();
    }
}

/// A origem das páginas LOCAIS (`http://tauri.localhost/` no Windows), lida da webview do topo ao criar a janela: é
/// para lá que a aba de um motor que caiu volta ("religando…").
static URL_LOCAL: std::sync::OnceLock<tauri::Url> = std::sync::OnceLock::new();

fn navegar(app: &tauri::AppHandle, m: Modulo, url: tauri::Url) {
    let alvo = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(wv) = alvo.get_webview(m.rotulo()) {
            let _ = wv.navigate(url);
        }
    });
}

/// O motor atendeu: a aba vai ao painel dele. ⚠️ A porta abre um pouco antes de o servidor aceitar: um respiro evita
/// a página de erro do WebView2.
fn levar_ao_painel(app: &tauri::AppHandle, m: Modulo) {
    let Some((porta, caminho)) = m.motor() else { return };
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if let Ok(url) = format!("http://127.0.0.1:{porta}{caminho}").parse::<tauri::Url>() {
            navegar(&app, m, url);
        }
    });
}

/// O motor caiu: a aba volta à página local, que diz "religando…" (o painel morto mostraria a página de erro).
fn levar_a_espera(app: &tauri::AppHandle, m: Modulo) {
    if let Some(url) = URL_LOCAL.get().and_then(|b| b.join(&format!("modulo.html?m={}", m.rotulo())).ok()) {
        navegar(app, m, url);
    }
}

fn parar_motores(app: &tauri::AppHandle) {
    // ⛔ Antes de matar: o supervisor religaria o que acabou de cair.
    supervisor::ENCERRANDO.store(true, std::sync::atomic::Ordering::SeqCst);
    // ⭐ Cada passo no log, com o tempo: se a janela prender AQUI (no fechamento), o log diz em qual motor.
    for (m, mut filho) in app.state::<Motores>().0.lock().unwrap().drain(..) {
        let t = std::time::Instant::now();
        let pid = filho.id();
        let morto = filho.kill();
        let fim = filho.wait();
        registrar(&format!("motor de {} (pid {pid}) encerrado: kill {:?}, wait {:?}, {} ms",
                           m.rotulo(), morto.is_ok(), fim.map(|s| s.code()).ok(), t.elapsed().as_millis()));
    }
}

// ── a janela ──────────────────────────────────────────────────────────────────

#[derive(Serialize, serde::Deserialize, Default)]
struct Preferencias {
    #[serde(default)]
    janela: Option<Geometria>,
    #[serde(default)]
    aba: Option<String>,
    /// ⭐ Onde o app começa (autor, 2026-11-07): um módulo (`assistir`, `preparar`, `conformar`) ou `ultima` (a aba em
    /// que ele estava ao fechar). Sem escolha, o Assistir.
    #[serde(default)]
    inicio: Option<String>,
}

/// As escolhas de "onde o app começa", na ordem da lista das configurações.
const INICIOS: [&str; 4] = ["assistir", "preparar", "conformar", "ultima"];

/// A aba em que o app abre: a escolhida em Geral (padrão: Assistir) ou, com `ultima`, a lembrada.
fn aba_inicial(p: &Preferencias) -> Modulo {
    match p.inicio.as_deref() {
        Some("ultima") => p.aba.as_deref().and_then(Modulo::de).unwrap_or(Modulo::Assistir),
        Some(m) => Modulo::de(m).unwrap_or(Modulo::Assistir),
        None => Modulo::Assistir,
    }
}

#[derive(Serialize, serde::Deserialize, Clone, Copy, Debug)]
struct Geometria {
    x: i32,
    y: i32,
    w: u32,
    h: u32,
    #[serde(default)]
    max: bool,
}

/// A pasta de dados do Ciclo Assist — a MESMA de `cicloassist/servico/config.py::pasta()`.
/// `<dados>/ocupado-<módulo>.json`: o aviso "vou ficar mudo" do motor (ver `supervisor::ler_ocupado`).
fn arquivo_ocupado(m: Modulo) -> Option<PathBuf> {
    Some(pasta_dados()?.join(format!("ocupado-{}.json", m.rotulo())))
}

fn pasta_dados() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("CICLOASSIST_DADOS") {
        return Some(PathBuf::from(p));
    }
    Some(if cfg!(windows) {
        PathBuf::from(std::env::var_os("LOCALAPPDATA")?).join("CicloAssist")
    } else {
        PathBuf::from(std::env::var_os("HOME")?).join("Library/Application Support/CicloAssist")
    })
}

fn ler_preferencias() -> Preferencias {
    pasta_dados()
        .and_then(|p| std::fs::read_to_string(p.join("app.json")).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn gravar_preferencias(app: &tauri::AppHandle) {
    let st = app.state::<EstadoApp>();
    let (geom, aba) = {
        let e = st.0.lock().unwrap();
        (e.antes_de_alargar.or(e.geom), e.aba)
    };
    let mut p = ler_preferencias();
    if geom.is_some() {
        p.janela = geom;
    }
    if let Some(a) = aba {
        p.aba = Some(a.rotulo().into());
    }
    let Some(pasta) = pasta_dados() else { return };
    let _ = std::fs::create_dir_all(&pasta);
    if let Ok(t) = serde_json::to_string_pretty(&p) {
        let _ = std::fs::write(pasta.join("app.json"), t);
    }
}

/// ⭐ O app ABRE SEMPRE no tamanho padrão, no meio do monitor principal (autor, 2026-11-26: "vamos iniciar com um
/// tamanho padrão" — a janela voltava larga, com a geometria lembrada de um alargamento à mão). A geometria segue
/// gravada no `app.json` ao sair (a do alargamento da revisão é desfeita), mas não é mais lida ao abrir.
fn posicionar(janela: &tauri::Window) {
    use tauri::{PhysicalPosition, PhysicalSize};

    let monitores = janela.available_monitors().unwrap_or_default();
    let Some(m) = janela.primary_monitor().ok().flatten().or_else(|| monitores.into_iter().next()) else { return };
    let a = *m.work_area();
    let esc = m.scale_factor();
    let w = ((LARGURA * esc) as u32).min(a.size.width);
    let h = ((ALTURA * esc) as u32).min((a.size.height as f64 * FRACAO_DA_ALTURA) as u32);
    let _ = janela.set_size(PhysicalSize::new(w, h));
    // a moldura (barra de título) conta na conta do lugar: medida depois do 1º set_size
    let (dw, dh) = match (janela.outer_size().ok(), janela.inner_size().ok()) {
        (Some(f), Some(d)) => (f.width.saturating_sub(d.width), f.height.saturating_sub(d.height)),
        _ => (0, 0),
    };
    let y = a.position.y + (a.size.height.saturating_sub(h + dh) / 2) as i32;
    let x = a.position.x + (a.size.width.saturating_sub(w + dw) / 2) as i32;
    let _ = janela.set_position(PhysicalPosition::new(x, y));
}

/// A altura da barra de título que as webviews têm de pular, em pixels lógicos.
///
/// ⛔ macOS (medido em 2026-11-06, Tauri 2.12.5): numa janela de várias webviews a área de conteúdo é a moldura INTEIRA
/// — o `inner_size` devolve a altura com a barra de título (999 = o `outer_size`) e o y 0 fica ATRÁS dela. O módulo
/// nascia 28 px alto demais e cobria a régua de abas (Preparar · Assistir · Conformar · Entregar), e a página do topo
/// era empurrada para baixo da barra. A medida vem do próprio AppKit: moldura − `contentLayoutRect`.
/// No Windows a área de conteúdo já exclui a barra: 0.
#[cfg(target_os = "macos")]
fn barra_de_titulo(janela: &tauri::Window) -> f64 {
    use objc2::{msg_send, runtime::AnyObject};
    use objc2_foundation::NSRect;
    let Ok(p) = janela.ns_window() else { return 0.0 };
    let w = p as *mut AnyObject;
    if w.is_null() {
        return 0.0;
    }
    // SAFETY: `ns_window` é o NSWindow vivo desta janela; chamado na thread principal (eventos e criação da janela).
    let (moldura, util): (NSRect, NSRect) = unsafe { (msg_send![&*w, frame], msg_send![&*w, contentLayoutRect]) };
    (moldura.size.height - util.size.height).max(0.0)
}

#[cfg(not(target_os = "macos"))]
fn barra_de_titulo(_janela: &tauri::Window) -> f64 {
    0.0
}

/// O topo em cima, o rodapé embaixo, a aba visível no meio. Chamado a cada mudança de tamanho.
fn arrumar(app: &tauri::AppHandle) {
    let Some(janela) = app.get_window(JANELA) else { return };
    let Ok(tam) = janela.inner_size() else { return };
    let escala = janela.scale_factor().unwrap_or(1.0);
    let (w, h) = (tam.width as f64 / escala, tam.height as f64 / escala);
    let t = barra_de_titulo(&janela);
    let meio = (h - t - ALTURA_DO_TOPO - ALTURA_DO_RODAPE).max(0.0);
    if let Some(topo) = app.get_webview(TOPO) {
        let _ = topo.set_position(LogicalPosition::new(0.0, t));
        let _ = topo.set_size(LogicalSize::new(w, ALTURA_DO_TOPO));
    }
    if let Some(pe) = app.get_webview(RODAPE) {
        let _ = pe.set_position(LogicalPosition::new(0.0, t + ALTURA_DO_TOPO + meio));
        let _ = pe.set_size(LogicalSize::new(w, ALTURA_DO_RODAPE));
    }
    for m in Modulo::TODOS {
        if let Some(wv) = app.get_webview(m.rotulo()) {
            let _ = wv.set_position(LogicalPosition::new(0.0, t + ALTURA_DO_TOPO));
            let _ = wv.set_size(LogicalSize::new(w, meio));
        }
    }
}

/// Mostra a aba pedida e esconde as outras. ⭐ Esconder, nunca recarregar: o trabalho de cada módulo segue vivo.
/// ⭐ A batida das abas ESCONDIDAS, dada daqui a cada pulso do supervisor.
///
/// ⛔ macOS (medido em 2026-11-06): o WebKit espaça os temporizadores de uma webview escondida até pará-los — a
/// presença da Preparar no Sincronizar oscilou e, a partir de ~50 s escondida, morreu de vez. A Preparar é quem monta no
/// Premiere o que o chat do Assist pede (a fila `/nlejob` do Sincronizar); escondida e muda, o sync recusava com 412. O
/// `eval` de fora não é espaçado: a página roda a batida dela quando o app manda.
pub(crate) fn bater_nas_escondidas(app: &tauri::AppHandle) {
    let visivel = app.state::<EstadoApp>().0.lock().ok().and_then(|e| e.aba);
    for m in Modulo::TODOS {
        let funcao = match m {
            Modulo::Preparar => "sincBater",
            _ => continue,
        };
        if Some(m) == visivel {
            continue; // visível, a página bate sozinha
        }
        if let Some(wv) = app.get_webview(m.rotulo()) {
            let _ = wv.eval(format!("window.{funcao} && window.{funcao}()"));
        }
    }
}

fn mostrar_aba(app: &tauri::AppHandle, aba: Modulo) {
    app.state::<EstadoApp>().0.lock().unwrap().aba = Some(aba);
    registrar(&format!("aba: {}", aba.rotulo()));
    for m in Modulo::TODOS {
        if let Some(wv) = app.get_webview(m.rotulo()) {
            let _ = if m == aba { wv.show() } else { wv.hide() };
        }
    }
    if let Some(wv) = app.get_webview(aba.rotulo()) {
        let _ = wv.set_focus();
    }
    if let Some(topo) = app.get_webview(TOPO) {
        let _ = topo.eval(format!("window.marcarAba && window.marcarAba('{}')", aba.rotulo()));
    }
}

#[tauri::command]
fn trocar_aba(app: tauri::AppHandle, aba: String) -> Result<(), String> {
    let m = Modulo::de(&aba).ok_or("aba desconhecida")?;
    mostrar_aba(&app, m);
    Ok(())
}

#[derive(Serialize)]
struct EstadoDoTopo {
    aba: Option<Modulo>,
    fixada: bool,
    versao: String,
}

#[tauri::command]
fn estado_do_topo(app: tauri::AppHandle) -> EstadoDoTopo {
    let st = app.state::<EstadoApp>();
    let e = st.0.lock().unwrap();
    EstadoDoTopo { aba: e.aba, fixada: e.fixada, versao: app.package_info().version.to_string() }
}

/// Um GET ao motor do Assist, sem crate de HTTP: o literal `127.0.0.1` (a regra do `localhost` no Windows) e o corpo
/// depois do cabeçalho. ⚠️ `Sec-Fetch-Site: same-origin` porque o porteiro do serviço só atende o painel — e este app
/// é o dono do motor (`--app`), não uma página qualquer.
fn pedir_ao_assist(caminho: &str) -> Option<String> {
    use std::io::{Read, Write};
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};
    use std::time::Duration;
    let alvo = SocketAddr::from((Ipv4Addr::LOCALHOST, 7824));
    let mut s = TcpStream::connect_timeout(&alvo, Duration::from_millis(500)).ok()?;
    let _ = s.set_read_timeout(Some(Duration::from_secs(10)));
    let pedido = format!(
        "GET {caminho} HTTP/1.1\r\nHost: 127.0.0.1:7824\r\nSec-Fetch-Site: same-origin\r\nConnection: close\r\n\r\n"
    );
    s.write_all(pedido.as_bytes()).ok()?;
    let mut bruto = Vec::new();
    let _ = s.read_to_end(&mut bruto);
    let texto = String::from_utf8_lossy(&bruto).into_owned();
    let (cabeca, corpo) = texto.split_once("\r\n\r\n")?;
    cabeca.starts_with("HTTP/1.1 200").then(|| corpo.to_string())
}

/// O estado da conexão com os NLEs, para o topo (`/conexao` do Assist: o programa, a versão, o projeto).
/// ⛔ `async`: o pedido pode levar segundos (o MC fechado custa 3 s), e um comando síncrono seguraria a interface.
#[tauri::command]
async fn conexao() -> Option<serde_json::Value> {
    pedir_ao_assist("/conexao").and_then(|c| serde_json::from_str(&c).ok())
}

/// O estado de cada motor do conjunto (o supervisor), para o topo e as abas.
#[tauri::command]
fn estado_dos_motores(app: tauri::AppHandle) -> Vec<supervisor::Saude> {
    supervisor::estado(&app)
}

/// O botão "tentar de novo" de um motor que o supervisor desistiu de religar.
#[tauri::command]
fn religar_motor(app: tauri::AppHandle, modulo: String) -> Result<(), String> {
    let m = Modulo::de(&modulo).ok_or_else(|| format!("módulo desconhecido: {modulo}"))?;
    std::thread::spawn(move || supervisor::religar_a_pedido(&app, m));
    Ok(())
}

#[tauri::command]
fn fixar_janela(app: tauri::AppHandle, sim: bool) {
    fixar(&app, sim);
}

/// A engrenagem ÚNICA: abre a JANELA de configurações (`ajustes.rs`, autor, 2026-11-07) na seção da aba visível.
/// ⛔ `async`: criar janela num comando síncrono trava no Windows (o comando roda na thread da janela).
#[tauri::command]
async fn engrenagem(app: tauri::AppHandle) -> Result<(), String> {
    // ⭐ Sempre em Geral (autor, 2026-11-07): antes abria na seção da aba que estava na tela.
    ajustes::abrir(&app, "geral")
}

/// A página das configurações pede a seção: `"local"`, `"modulo"` ou `"fora"` (ver `ajustes::mostrar_secao`).
#[tauri::command]
async fn ajustes_secao(app: tauri::AppHandle, secao: String) -> Result<&'static str, String> {
    ajustes::mostrar_secao(&app, &secao)
}

#[derive(Serialize)]
struct Geral {
    versao: String,
    fixada: bool,
    pasta: Option<String>,
    inicio: String,
}

/// Grava onde o app começa (a lista de Geral). Só os valores de `INICIOS`.
#[tauri::command]
fn ajustes_inicio(inicio: String) -> Result<(), String> {
    if !INICIOS.contains(&inicio.as_str()) {
        return Err(format!("início desconhecido: {inicio}"));
    }
    let mut p = ler_preferencias();
    p.inicio = Some(inicio.clone());
    let pasta = pasta_dados().ok_or("não sei onde fica a pasta de dados")?;
    let _ = std::fs::create_dir_all(&pasta);
    let t = serde_json::to_string_pretty(&p).map_err(|e| e.to_string())?;
    std::fs::write(pasta.join("app.json"), t).map_err(|e| e.to_string())?;
    registrar(&format!("o app passa a começar em: {inicio}"));
    Ok(())
}

/// O que a seção Geral mostra.
#[tauri::command]
fn ajustes_geral(app: tauri::AppHandle) -> Geral {
    let fixada = app.state::<EstadoApp>().0.lock().unwrap().fixada;
    Geral {
        versao: app.package_info().version.to_string(),
        fixada,
        pasta: pasta_dados().map(|p| p.display().to_string()),
        inicio: ler_preferencias().inicio.unwrap_or_else(|| "assistir".into()),
    }
}

/// Abre a pasta de dados do Ciclo Assist no Finder/Explorer. Caminho do próprio app: não há canal para outro.
#[tauri::command]
fn abrir_pasta_de_dados() -> Result<(), String> {
    let pasta = pasta_dados().ok_or("não sei onde fica a pasta de dados")?;
    let _ = std::fs::create_dir_all(&pasta);
    tauri_plugin_opener::open_path(&pasta, None::<&str>).map_err(|e| e.to_string())
}

/// Abre o perfil do autor no NAVEGADOR do sistema. Endereço fixo no binário: não há canal para outra URL.
#[tauri::command]
fn abrir_autor(app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener().open_url(AUTOR_URL, None::<&str>).map_err(|e| e.to_string())
}

/// Cria a janela, a barra de abas e uma webview por módulo — todas de uma vez, porque o alvo de arrasto só alcança as
/// webviews que já existem quando é instalado (`arrasto_win::instalar`).
fn criar_janela(app: &tauri::AppHandle) -> Result<(), String> {
    let janela = tauri::window::WindowBuilder::new(app, JANELA)
        .title("Ciclo Assist")
        .inner_size(LARGURA, ALTURA)
        .min_inner_size(380.0, 480.0)
        .resizable(true)
        .visible(false)
        .build()
        .map_err(|e| format!("não consegui abrir a janela: {e}"))?;
    posicionar(&janela);
    let tam = janela.inner_size().map_err(|e| e.to_string())?;
    let escala = janela.scale_factor().unwrap_or(1.0);
    let (w, h) = (tam.width as f64 / escala, tam.height as f64 / escala);

    let t = barra_de_titulo(&janela);
    let meio = (h - t - ALTURA_DO_TOPO - ALTURA_DO_RODAPE).max(0.0);
    let local = |rotulo: &str, pagina: String, y: f64, alto: f64| {
        let construtor = tauri::webview::WebviewBuilder::new(rotulo, WebviewUrl::App(pagina.into()));
        // ⚠️ No Windows o tratador do Tauri/WebView2 fica DESLIGADO (ele pede o arquivo e o MC EXPORTA — `arrasto_win`);
        // no Mac ele fica LIGADO nas webviews de módulo, e o `arrasto_mac` repassa o gesto (o MobID do MC, os caminhos).
        let construtor = if cfg!(target_os = "macos") && Modulo::de(rotulo).is_some() {
            construtor
        } else {
            construtor.disable_drag_drop_handler()
        };
        janela
            .add_child(
                construtor,
                LogicalPosition::new(0.0, y),
                LogicalSize::new(w, alto),
            )
            .map_err(|e| format!("não consegui criar {rotulo}: {e}"))
    };
    let topo = local(TOPO, "topo.html".into(), t, ALTURA_DO_TOPO)?;
    if let Ok(u) = topo.url() {
        let _ = URL_LOCAL.set(u);
    }
    let mut webviews = vec![
        topo,
        local(RODAPE, "rodape.html".into(), t + ALTURA_DO_TOPO + meio, ALTURA_DO_RODAPE)?,
    ];
    for m in Modulo::TODOS {
        // ⭐ Nasce na página LOCAL do módulo ("ligando…" ou "em breve") e vai ao painel quando o motor atende.
        let wv = local(m.rotulo(), format!("modulo.html?m={}", m.rotulo()), t + ALTURA_DO_TOPO, meio)?;
        #[cfg(target_os = "macos")]
        arrasto_mac::instalar(&wv);
        webviews.push(wv);
    }
    // ⭐ Padrão: o Assistir (na sub-aba Assistir, a primeira do painel dele); a escolha mora em ⚙ › Geral (2026-11-07).
    mostrar_aba(app, aba_inicial(&ler_preferencias()));
    let _ = janela.show();
    let _ = janela.set_focus();
    #[cfg(windows)]
    arrasto_win::instalar(&janela, &webviews);
    let _ = webviews;
    Ok(())
}

fn fixar(app: &tauri::AppHandle, sim: bool) {
    registrar(&format!("pino: {sim}"));
    if let Some(j) = app.get_window(JANELA) {
        let _ = j.set_always_on_top(sim);
    }
    app.state::<EstadoApp>().0.lock().unwrap().fixada = sim;
    if let Some(topo) = app.get_webview(TOPO) {
        let _ = topo.eval(format!("window.marcarPino && window.marcarPino({sim})"));
    }
    ajustes::acompanhar_o_pino(app, sim);
    oficina::acompanhar_o_pino(app, sim);
    carta::acompanhar_o_pino(app, sim);
}

/// A revisão de mídias do De Lá Pra Cá pede a janela LARGA (`--janela-larga`) e a devolve (`--janela-painel`): alarga
/// para a esquerda, mantendo a borda direita, e volta à geometria de antes.
fn alargar(app: &tauri::AppHandle, larga: bool) {
    use tauri::{PhysicalPosition, PhysicalSize};
    let Some(j) = app.get_window(JANELA) else { return };
    let st = app.state::<EstadoApp>();
    if !larga {
        let antes = st.0.lock().unwrap().antes_de_alargar.take();
        if let Some(g) = antes {
            let _ = j.set_size(PhysicalSize::new(g.w, g.h));
            let _ = j.set_position(PhysicalPosition::new(g.x, g.y));
        }
        return;
    }
    if j.is_maximized().unwrap_or(false) {
        return;
    }
    let (Ok(p), Ok(t), Ok(f)) = (j.outer_position(), j.inner_size(), j.outer_size()) else { return };
    {
        let mut e = st.0.lock().unwrap();
        if e.antes_de_alargar.is_none() {
            e.antes_de_alargar = Some(Geometria { x: p.x, y: p.y, w: t.width, h: t.height, max: false });
        }
    }
    let Some(m) = j.current_monitor().ok().flatten() else { return };
    let a = *m.work_area();
    let dw = f.width.saturating_sub(t.width);
    let w = ((LARGURA_LARGA * m.scale_factor()) as u32).min(a.size.width.saturating_sub(dw));
    if w <= t.width {
        return;
    }
    let x = (p.x + f.width as i32 - (w + dw) as i32).max(a.position.x);
    let _ = j.set_size(PhysicalSize::new(w, t.height));
    let _ = j.set_position(PhysicalPosition::new(x, p.y));
}

fn sair(app: &tauri::AppHandle) {
    registrar("sair pedido");
    gravar_preferencias(app);
    parar_motores(app);
    app.exit(0);
}

#[tauri::command]
fn encerrar(app: tauri::AppHandle) {
    sair(&app);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        // ⚠️ Uma instância só, e é por aqui que chegam os recados dos motores (o executável reinvocado).
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            registrar(&format!("reinvocado com {:?}", args.get(1..).unwrap_or(&[])));
            let tem = |a: &str| args.iter().any(|x| x == a);
            if tem("--fixar") || tem("--soltar") || tem("--fixar-mc") || tem("--soltar-mc") {
                fixar(app, tem("--fixar") || tem("--fixar-mc"));
            } else if tem("--encerrar") {
                sair(app);
            } else if tem("--fluxos-e-agentes") {
                // ⛔ Fora da thread da janela: criar janela nela trava no Windows (a mesma razão do `async` da engrenagem).
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = oficina::abrir(&app) {
                        registrar(&e);
                    }
                });
            } else if tem("--carta-aberta") {
                // ⛔ Fora da thread da janela, pelo mesmo motivo do `--fluxos-e-agentes`.
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = carta::abrir(&app) {
                        registrar(&e);
                    }
                });
            } else if tem("--conformar") {
                // ⭐ A Carta Aberta pediu "Conformar com De Lá Pra Cá" (proposta Baselight no app, etapa 3): a aba
                // Conformar à frente; o painel dele pega o pedido sozinho (`/receber/a-conformar`).
                mostrar_aba(app, Modulo::Conformar);
                if let Some(j) = app.get_window(JANELA) {
                    let _ = j.unminimize();
                    let _ = j.show();
                    let _ = j.set_focus();
                }
            } else if tem("--janela-larga") || tem("--janela-painel") {
                alargar(app, tem("--janela-larga"));
            } else if tem("--revisao") || tem("--fechar-revisao") {
                // o De Lá Pra Cá de antes da janela única: a revisão já mora DENTRO do painel dele
            } else if let Some(j) = app.get_window(JANELA) {
                let _ = j.unminimize();
                let _ = j.show();
                let _ = j.set_focus();
            }
        }))
        .manage(Motores::default())
        .manage(supervisor::Supervisor::default())
        .manage(EstadoApp::default())
        .setup(|app| {
            let _ = APP.set(app.handle().clone());
            registro::iniciar(pasta_dados());
            registro::vigiar_a_thread_da_janela(app.handle().clone());
            // Abrir o app É ligar os módulos. Falhar num não impede os outros: a aba dele diz o estado.
            let mut iniciais = vec![];
            for m in Modulo::TODOS {
                if m.motor().is_none() {
                    continue;
                }
                let r = subir_motor(app.handle(), m, false);
                if let Err(e) = &r {
                    registrar(e);
                }
                iniciais.push((m, r));
            }
            if let Err(e) = criar_janela(app.handle()) {
                registrar(&e);
            }
            // ⭐ Quem leva cada aba ao painel (e a religa, se o motor cair) é o supervisor.
            supervisor::iniciar(app.handle().clone(), iniciais);
            Ok(())
        })
        .on_window_event(|janela, evento| {
            if janela.label() == ajustes::JANELA {
                if let tauri::WindowEvent::Resized(_) = evento {
                    ajustes::arrumar(janela.app_handle());
                }
                return;
            }
            if janela.label() != JANELA {
                return;
            }
            let app = janela.app_handle();
            match evento {
                tauri::WindowEvent::Resized(_) | tauri::WindowEvent::Moved(_) => {
                    arrumar(app);
                    if !janela.is_minimized().unwrap_or(false) {
                        if let (Ok(p), Ok(t)) = (janela.outer_position(), janela.inner_size()) {
                            let g = Geometria { x: p.x, y: p.y, w: t.width, h: t.height, max: janela.is_maximized().unwrap_or(false) };
                            let st = app.state::<EstadoApp>();
                            let mut e = st.0.lock().unwrap();
                            if e.antes_de_alargar.is_none() {
                                e.geom = Some(g);
                            }
                        }
                    }
                }
                // ⚠️ Fechar a janela encerra os motores que ESTE app subiu. Os motores Python também se vigiam (`--pai`)
                // e não morrem no meio de um trabalho: terminam e então saem.
                tauri::WindowEvent::CloseRequested { .. } => registrar("fechar pedido (CloseRequested)"),
                tauri::WindowEvent::Destroyed => {
                    // as configurações não vivem sem a janela principal (e sem os motores, nada nelas responde)
                    if let Some(j) = app.get_window(ajustes::JANELA) {
                        let _ = j.destroy();
                    }
                    oficina::fechar(app);
                    carta::fechar(app);
                    registrar("janela destruída: gravando preferências e encerrando os motores");
                    gravar_preferencias(app);
                    parar_motores(app);
                    registrar("motores encerrados");
                }
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![
            trocar_aba,
            estado_do_topo,
            conexao,
            fixar_janela,
            estado_dos_motores,
            religar_motor,
            engrenagem,
            ajustes_secao,
            ajustes_geral,
            ajustes_inicio,
            abrir_pasta_de_dados,
            abrir_autor,
            encerrar
        ])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o Ciclo Assist");
}

#[cfg(test)]
mod testes {
    use super::*;

    #[test]
    fn as_quatro_abas_na_ordem_do_autor() {
        let nomes: Vec<_> = Modulo::TODOS.iter().map(|m| m.rotulo()).collect();
        assert_eq!(nomes, ["preparar", "assistir", "conformar", "entregar"]);
        assert_eq!(Modulo::Entregar.motor(), None);
        assert_eq!(Modulo::Assistir.motor().unwrap().0, 7824);
    }

    #[test]
    fn o_app_comeca_no_assistir_salvo_escolha() {
        let p = |inicio: Option<&str>, aba: Option<&str>| Preferencias {
            janela: None, aba: aba.map(Into::into), inicio: inicio.map(Into::into) };
        assert_eq!(aba_inicial(&p(None, Some("conformar"))), Modulo::Assistir, "sem escolha: Assistir, não a última");
        assert_eq!(aba_inicial(&p(Some("preparar"), Some("conformar"))), Modulo::Preparar);
        assert_eq!(aba_inicial(&p(Some("ultima"), Some("conformar"))), Modulo::Conformar);
        assert_eq!(aba_inicial(&p(Some("ultima"), None)), Modulo::Assistir);
        assert_eq!(aba_inicial(&p(Some("lixo"), None)), Modulo::Assistir);
        for i in INICIOS {
            assert!(i == "ultima" || Modulo::de(i).is_some(), "{i}");
        }
    }

    #[test]
    fn todo_modulo_abre_embutido() {
        // a moldura é do guarda-chuva: sem `embutido=1`, cada aba mostraria a dela por cima
        for m in Modulo::TODOS {
            if let Some((_, caminho)) = m.motor() {
                assert!(caminho.contains("embutido=1"), "{caminho}");
            }
        }
    }

    #[test]
    fn acha_a_pasta_dos_apps_e_os_motores() {
        let Some(apps) = pasta_dos_apps() else { panic!("não achei a pasta dos apps") };
        assert!(apps.join("_CICLO ASSIST").is_dir(), "{apps:?}");
        if python_do(&apps.join("_CICLO ASSIST")).is_file() {
            let (_, args, cwd) = comando_do_motor(Modulo::Assistir).expect("o motor do Assist");
            assert_eq!(&args[..2], ["-m", "cicloassist.servico"]);
            assert!(cwd.ends_with("_CICLO ASSIST"));
        }
        // ⭐ Fase 2: o Conformar sobe o De Lá Pra Cá do módulo deste repo, não a pasta `_DeLaPraCa`.
        if python_do(&apps.join("_CICLO ASSIST/modulos/conformar")).is_file() {
            let (_, args, cwd) = comando_do_motor(Modulo::Conformar).expect("o motor do Conformar");
            assert!(args[0].ends_with("plugins/media-composer/servico/main.py"), "{args:?}");
            assert!(cwd.ends_with("modulos/conformar"), "{cwd:?}");
        }
        // ⭐ A Preparar sobe o servidor Python do Sincronizar (o Sincronizar em Rust foi aposentado em 2026-11-07).
        if python_do_sincronizar().is_some() {
            let (_, args, cwd) = comando_do_motor(Modulo::Preparar).expect("o motor da Preparar");
            assert!(args[0].ends_with("servidor.py"), "{args:?}");
            assert_eq!(&args[1..2], ["--pai"]);
            assert!(cwd.ends_with("_CICLO ASSIST"));
        }
    }
}
