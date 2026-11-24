//! O log do APP em arquivo — e o pulso da thread da janela.
//!
//! ⭐ Por que existe (2026-10-29, `docs/plano/2026-10-29-preferencias-e-a-janela-travada.md`): a janela ficou "não
//! respondendo" e nada contou onde. Este app escrevia com `eprintln!`, que sem console some. Agora cada evento que
//! importa para um travamento (abrir, fechar, encerrar motores, trocar de aba, o pino) vai para
//! `<pasta de dados>/logs/app.log`, com a hora LOCAL (a mesma dos logs do serviço) e a thread que escreveu.
//!
//! ⭐ **O pulso:** uma thread de fundo pede à thread da janela, a cada `PULSO`, para anotar a hora. Se ela não anotar por
//! mais de `PRESA`, a janela está presa — e o log diz DESDE QUANDO, que é o que faltou no primeiro travamento. O vigia do
//! serviço (`cicloassist/servico/travamento.py`) grava o minidump; este pulso grava o começo e o fim do episódio.

use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const PULSO: Duration = Duration::from_secs(5);
const PRESA: Duration = Duration::from_secs(15);

static ARQUIVO: Mutex<Option<PathBuf>> = Mutex::new(None);

/// Onde o log mora: `<pasta de dados>/logs/app.log` (ao lado do `cicloassist.log` do serviço).
pub fn iniciar(pasta_dados: Option<PathBuf>) {
    let Some(pasta) = pasta_dados.map(|p| p.join("logs")) else { return };
    let _ = std::fs::create_dir_all(&pasta);
    *ARQUIVO.lock().unwrap() = Some(pasta.join("app.log"));
    registrar(&format!("app aberto (pid {}, versão {})", std::process::id(), env!("CARGO_PKG_VERSION")));
}

/// Uma linha no log. Nunca falha para quem chama: log que derruba o app é pior que log nenhum.
pub fn registrar(msg: &str) {
    let linha = format!("{}  [{}] {msg}\n", agora(), thread());
    eprint!("[CicloAssist] {linha}");
    let caminho = ARQUIVO.lock().ok().and_then(|g| g.clone());
    if let Some(c) = caminho {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(c) {
            let _ = f.write_all(linha.as_bytes());
        }
    }
}

fn thread() -> String {
    let t = std::thread::current();
    t.name().map(str::to_owned).unwrap_or_else(|| format!("{:?}", t.id()))
}

#[cfg(windows)]
fn agora() -> String {
    #[repr(C)]
    #[derive(Default)]
    struct SystemTime {
        ano: u16,
        mes: u16,
        _dia_da_semana: u16,
        dia: u16,
        hora: u16,
        minuto: u16,
        segundo: u16,
        ms: u16,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetLocalTime(t: *mut SystemTime);
    }
    let mut t = SystemTime::default();
    // SAFETY: GetLocalTime só preenche a estrutura que recebe.
    unsafe { GetLocalTime(&mut t) };
    format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02},{:03}", t.ano, t.mes, t.dia, t.hora, t.minuto, t.segundo, t.ms)
}

#[cfg(not(windows))]
fn agora() -> String {
    // ⚠️ Fora do Windows sem crate de data: segundos desde a época (`pendente` — a hora local no Mac).
    let d = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
    format!("t={}.{:03}", d.as_secs(), d.subsec_millis())
}

/// O pulso da thread da janela. `INICIO` é o relógio do processo; `ULTIMO` guarda (em ms desde ele) a última vez que a
/// thread da janela atendeu.
static ULTIMO_MS: AtomicU64 = AtomicU64::new(0);

pub fn vigiar_a_thread_da_janela(app: tauri::AppHandle) {
    let inicio = Instant::now();
    let _ = std::thread::Builder::new().name("pulso-da-janela".into()).spawn(move || {
        let mut presa_desde: Option<String> = None;
        loop {
            let pedido = inicio.elapsed().as_millis() as u64;
            let _ = app.run_on_main_thread(move || {
                ULTIMO_MS.store(inicio.elapsed().as_millis() as u64, Ordering::Relaxed);
            });
            std::thread::sleep(PULSO);
            let ultimo = ULTIMO_MS.load(Ordering::Relaxed);
            // Quanto tempo desde a última vez que a thread da janela atendeu um pedido nosso.
            let atraso = Duration::from_millis((inicio.elapsed().as_millis() as u64).saturating_sub(ultimo));
            if ultimo < pedido && atraso >= PRESA {
                if presa_desde.is_none() {
                    registrar(&format!("⛔ a thread da JANELA não atende há {} s — presa", atraso.as_secs()));
                    presa_desde = Some(format!("~{} s antes de {}", atraso.as_secs(), agora()));
                }
            } else if ultimo >= pedido {
                if let Some(desde) = presa_desde.take() {
                    registrar(&format!("a thread da janela voltou a atender (a trava começou {desde})"));
                }
            }
        }
    });
}
