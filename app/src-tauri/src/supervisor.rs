//! O SUPERVISOR dos motores: com o Ciclo Assist aberto, todos os apps do conjunto estão no ar.
//!
//! ⭐⭐ Decisão do autor (2026-11-02): *"se o ciclo assist está on, todos os apps do conjunto devem estar tbm, sincronizar, de
//! la pra ca, qualquer outro que venha a ser adicionado. se houver uma falha em um deles devem ser reiniciados sozinhos,
//! e se não puderem subir, devemos avisar ao usuário."*
//!
//! O que motivou: na prova da F1 o app foi morto à força e o De Lá Pra Cá caiu junto; reaberto, o conform falhou com
//! "o De Lá Pra Cá não respondeu" e ninguém o religava — o conselho do fluxo pediu ao editor para "abrir a aba".
//!
//! - Vigia a PORTA de cada motor (`Modulo::motor`), a cada `PULSO` (1 s enquanto algum está subindo). ⭐ Percorre
//!   `Modulo::TODOS`: um módulo novo com motor entra aqui sem uma linha a mais.
//! - Caiu → religa e leva a aba à página local ("religando…"); de pé de novo, a aba volta ao painel do motor.
//!   ⛔ "Caiu" é o PROCESSO ter saído (religa na hora, com o código) ou a porta muda por `TOLERANCIA_SEM_PORTA` com
//!   ele vivo — nunca uma conexão de 250 ms que falhou (2026-11-04: matar o serviço no meio de um turno apaga a
//!   conversa do editor e deixa a operação pela metade).
//! - Subindo há mais de `PRAZO_DE_SUBIR` sem abrir a porta, ou o processo saiu → nova tentativa.
//! - ⛔ No máximo `MAX_TENTATIVAS` em `JANELA_DE_TENTATIVAS`: um motor que morre na partida não pode virar um laço de
//!   processos. Passou disso, `Falhou` com o motivo, e o TOPO avisa com um botão "tentar de novo" (`religar_motor`).
//! - O estado vai para `<dados>/motores.json` a cada pulso: o serviço do Assist o lê (o conselho do fluxo sabe se o
//!   serviço que falhou já voltou).
//! - ⛔ `ENCERRANDO` para tudo antes de `parar_motores`: sem isso, fechar o app religaria o que ele acabou de matar.
//! ⚠️ Só a PORTA é vigiada: um motor que escuta e não responde (travado) não é detectado — não medido em campo.
//! ⛔ Motor ADOTADO (a porta já atendia quando o app abriu — o de um app anterior morto à força): sem filho nosso, a porta
//!   muda religa NA HORA (`filho_saiu`), em vez de esperar a tolerância de um processo vivo que não existe.
//! ⭐ Antes de religar um motor vivo e mudo, `diagnosticar` grava a fila da porta e a pilha dele (2026-11-07).

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::Manager;

use super::{
    diagnosticar, filho_saiu, levar_a_espera, levar_ao_painel, matar_filho, pasta_dados, porta_ocupada, registrar, subir_motor,
    Modulo,
};

pub const PULSO: Duration = Duration::from_secs(3);
pub const PULSO_SUBINDO: Duration = Duration::from_secs(1);
/// O Sincronizar sobe o sidecar Python: o mesmo prazo que a aba esperava antes (`ir_para_o_painel`, 90 s).
pub const PRAZO_DE_SUBIR: Duration = Duration::from_secs(90);
pub const JANELA_DE_TENTATIVAS: Duration = Duration::from_secs(600);
pub const MAX_TENTATIVAS: usize = 3;
/// ⭐ Um motor NO AR cujo processo continua vivo e não atende a porta tem este prazo antes de ser religado
/// (2026-11-04). Antes, UMA conexão de 250 ms que falhasse já o matava — e matar o serviço do Assist no meio de
/// um turno apaga a conversa do editor e deixa a operação pela metade. Processo que SAIU religa na hora.
pub const TOLERANCIA_SEM_PORTA: Duration = Duration::from_secs(15);
/// ⛔ O motor que vai ficar mudo DE PROPÓSITO avisa antes (2026-11-23): toda chamada da API do Resolve segura o GIL do
/// processo inteiro enquanto o Resolve trabalha, e a importação do PRODC (80 planos) passou dos 15 s — o motor do
/// Conformar foi religado 3 vezes e o conform morreu no meio. O motor grava `ocupado-<módulo>.json` em `<dados>`
/// (`{ate, motivo, pid}`, `aviso_ocupado.py` do Conformar); enquanto o prazo vale, porta muda não conta. Este teto
/// impede que um aviso errado (ou um motor travado de verdade) segure a vigia para sempre.
pub const TETO_OCUPADO: Duration = Duration::from_secs(30 * 60);

/// O aviso "vou ficar mudo" do motor, se valer AGORA: do processo que subimos (`pid`), com o prazo no futuro e dentro
/// do teto. Pura: o texto do arquivo, o pid do filho e o relógio (segundos desde 1970).
pub fn ler_ocupado(texto: &str, pid: Option<u32>, agora: u64) -> Option<(String, u64)> {
    let v: serde_json::Value = serde_json::from_str(texto).ok()?;
    let ate = v.get("ate")?.as_u64()?;
    if let (Some(p), Some(dono)) = (pid, v.get("pid").and_then(|x| x.as_u64())) {
        if u64::from(p) != dono {
            return None;
        }
    }
    if ate <= agora || ate > agora + TETO_OCUPADO.as_secs() {
        return None;
    }
    let motivo = v.get("motivo").and_then(|x| x.as_str()).unwrap_or("ocupado");
    Some((motivo.to_string(), ate - agora))
}

pub static ENCERRANDO: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Situacao {
    Subindo,
    NoAr,
    Religando,
    Falhou,
}

#[derive(Clone, Debug, Serialize)]
pub struct Saude {
    pub modulo: Modulo,
    pub nome: &'static str,
    pub porta: u16,
    pub situacao: Situacao,
    /// Quantas vezes foi religado nos últimos `JANELA_DE_TENTATIVAS`.
    pub tentativas: usize,
    pub maximo: usize,
    pub motivo: String,
    pub segundos: u64,
}

pub struct Vigia {
    pub situacao: Situacao,
    pub desde: Instant,
    pub tentativas: Vec<Instant>,
    pub motivo: String,
    /// No ar: desde quando a porta não atende (o processo vivo). `None` = atendeu no último pulso.
    pub sem_porta_desde: Option<Instant>,
    /// O aviso "vou ficar mudo" que está valendo (para dizer no log uma vez só).
    pub ocupado: Option<String>,
}

impl Vigia {
    pub fn nova(agora: Instant) -> Self {
        Vigia { situacao: Situacao::Subindo, desde: agora, tentativas: vec![], motivo: String::new(), sem_porta_desde: None,
                ocupado: None }
    }
}

/// O aviso do motor `m` no disco, valendo agora (`ler_ocupado`).
fn ocupado_agora(app: &tauri::AppHandle, m: Modulo) -> Option<(String, u64)> {
    let texto = std::fs::read_to_string(super::arquivo_ocupado(m)?).ok()?;
    let pid = app.state::<super::Motores>().0.lock().unwrap().iter().find(|(x, _)| *x == m).map(|(_, f)| f.id());
    let agora = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    ler_ocupado(&texto, pid, agora)
}

#[derive(Default)]
pub struct Supervisor(pub Mutex<HashMap<Modulo, Vigia>>);

#[derive(Debug, PartialEq)]
pub enum Acao {
    Nada,
    Subiu,
    Religar(String),
    Desistir(String),
}

/// O que fazer com um motor neste pulso. Pura: só o estado, o que se viu e o relógio.
pub fn decidir(v: &Vigia, no_ar: bool, saiu: Option<String>, agora: Instant) -> Acao {
    if no_ar {
        return if v.situacao == Situacao::NoAr { Acao::Nada } else { Acao::Subiu };
    }
    let motivo = match v.situacao {
        Situacao::Falhou => return Acao::Nada,
        Situacao::NoAr => match saiu {
            // ⛔ O processo MORREU (2026-11-04: o serviço do Assist caiu com access violation e isto dizia só "parou
            //   de responder"): religa na hora, dizendo como saiu.
            Some(c) => format!("o processo saiu ({c})"),
            None => match v.sem_porta_desde {
                Some(t) if agora.duration_since(t) >= TOLERANCIA_SEM_PORTA => format!(
                    "parou de responder há {} s (o processo continua vivo)", agora.duration_since(t).as_secs()),
                _ => return Acao::Nada,
            },
        },
        Situacao::Subindo | Situacao::Religando => match saiu {
            Some(c) => format!("o processo saiu ({c}) antes de abrir a porta"),
            None if agora.duration_since(v.desde) > PRAZO_DE_SUBIR => {
                format!("não abriu a porta em {} s", PRAZO_DE_SUBIR.as_secs())
            }
            None => return Acao::Nada,
        },
    };
    let recentes = v.tentativas.iter().filter(|t| agora.duration_since(**t) < JANELA_DE_TENTATIVAS).count();
    if recentes >= MAX_TENTATIVAS {
        Acao::Desistir(format!("{motivo}; já foi religado {recentes} vezes em {} min e não se manteve no ar",
                               JANELA_DE_TENTATIVAS.as_secs() / 60))
    } else {
        Acao::Religar(motivo)
    }
}

/// Liga a vigia (no `setup`, depois de subir os motores). `iniciais`: o resultado de cada `subir_motor`.
pub fn iniciar(app: tauri::AppHandle, iniciais: Vec<(Modulo, Result<(), String>)>) {
    {
        let st = app.state::<Supervisor>();
        let mut mapa = st.0.lock().unwrap();
        let agora = Instant::now();
        for (m, r) in iniciais {
            let mut v = Vigia::nova(agora);
            if let Err(e) = r {
                v.situacao = Situacao::Falhou;
                v.motivo = e;
            }
            mapa.insert(m, v);
        }
    }
    std::thread::spawn(move || loop {
        if ENCERRANDO.load(Ordering::SeqCst) {
            return;
        }
        let subindo = pulsar(&app);
        gravar(&app);
        super::bater_nas_escondidas(&app);
        std::thread::sleep(if subindo { PULSO_SUBINDO } else { PULSO });
    });
}

/// Um pulso. Devolve se algum motor está subindo (o próximo pulso vem mais cedo).
fn pulsar(app: &tauri::AppHandle) -> bool {
    let mut subindo = false;
    for m in Modulo::TODOS {
        let Some((porta, _)) = m.motor() else { continue };
        let no_ar = porta_ocupada(porta);
        let saiu = if no_ar { None } else { filho_saiu(app, m) };
        let ocupado = if no_ar || saiu.is_some() { None } else { ocupado_agora(app, m) };
        let st = app.state::<Supervisor>();
        let acao = {
            let mut mapa = st.0.lock().unwrap();
            let Some(v) = mapa.get_mut(&m) else { continue };
            if let (Some((o, resta)), Situacao::NoAr) = (&ocupado, v.situacao) {
                // Mudo de propósito: a tolerância só começa a contar quando o aviso acabar.
                if v.ocupado.as_deref() != Some(o.as_str()) {
                    registrar(&format!("motor de {}: porta muda, mas ele avisou: {o} (até {resta} s)", m.rotulo()));
                }
                v.ocupado = Some(o.clone());
                v.sem_porta_desde = None;
                continue;
            }
            v.ocupado = None;
            if no_ar {
                if v.sem_porta_desde.take().is_some() {
                    registrar(&format!("motor de {}: voltou a atender a porta", m.rotulo()));
                }
            } else if v.situacao == Situacao::NoAr && saiu.is_none() && v.sem_porta_desde.is_none() {
                v.sem_porta_desde = Some(Instant::now());
                registrar(&format!("motor de {}: não atendeu a porta (processo vivo); espero até {} s",
                                   m.rotulo(), TOLERANCIA_SEM_PORTA.as_secs()));
            }
            decidir(v, no_ar, saiu, Instant::now())
        };
        if ENCERRANDO.load(Ordering::SeqCst) {
            return false;
        }
        match acao {
            Acao::Nada => {}
            Acao::Subiu => {
                let mut mapa = st.0.lock().unwrap();
                if let Some(v) = mapa.get_mut(&m) {
                    registrar(&format!("motor de {} no ar ({:?} → no ar)", m.rotulo(), v.situacao));
                    v.situacao = Situacao::NoAr;
                    v.desde = Instant::now();
                    v.motivo.clear();
                }
                drop(mapa);
                levar_ao_painel(app, m);
            }
            Acao::Religar(motivo) => {
                if motivo.contains("processo continua vivo") {
                    diagnosticar(app, m);
                }
                religar(app, m, &motivo)
            }
            Acao::Desistir(motivo) => {
                registrar(&format!("motor de {}: desisti — {motivo}", m.rotulo()));
                let mut mapa = st.0.lock().unwrap();
                if let Some(v) = mapa.get_mut(&m) {
                    v.situacao = Situacao::Falhou;
                    v.motivo = motivo;
                }
            }
        }
        let mapa = st.0.lock().unwrap();
        if let Some(v) = mapa.get(&m) {
            subindo |= matches!(v.situacao, Situacao::Subindo | Situacao::Religando);
        }
    }
    subindo
}

/// Mata o que sobrou do motor e sobe outro. `motivo` vai para o log e para a aba.
pub fn religar(app: &tauri::AppHandle, m: Modulo, motivo: &str) {
    if ENCERRANDO.load(Ordering::SeqCst) {
        return;
    }
    registrar(&format!("motor de {}: {motivo} — religando", m.rotulo()));
    matar_filho(app, m);
    levar_a_espera(app, m);
    let r = subir_motor(app, m, true);
    let st = app.state::<Supervisor>();
    let mut mapa = st.0.lock().unwrap();
    let agora = Instant::now();
    let v = mapa.entry(m).or_insert_with(|| Vigia::nova(agora));
    v.tentativas.retain(|t| agora.duration_since(*t) < JANELA_DE_TENTATIVAS);
    v.tentativas.push(agora);
    v.desde = agora;
    match r {
        Ok(()) => {
            v.situacao = Situacao::Religando;
            v.sem_porta_desde = None;
            v.motivo = motivo.to_string();
        }
        Err(e) => {
            registrar(&e);
            v.situacao = Situacao::Falhou;
            v.motivo = e;
        }
    }
}

/// O botão "tentar de novo" do topo: o editor pediu — a conta de tentativas recomeça.
pub fn religar_a_pedido(app: &tauri::AppHandle, m: Modulo) {
    {
        let st = app.state::<Supervisor>();
        let mut mapa = st.0.lock().unwrap();
        if let Some(v) = mapa.get_mut(&m) {
            v.tentativas.clear();
        }
    }
    religar(app, m, "o editor pediu para tentar de novo");
}

pub fn estado(app: &tauri::AppHandle) -> Vec<Saude> {
    let st = app.state::<Supervisor>();
    let mapa = st.0.lock().unwrap();
    let agora = Instant::now();
    Modulo::TODOS
        .into_iter()
        .filter_map(|m| {
            let (porta, _) = m.motor()?;
            let v = mapa.get(&m)?;
            Some(Saude {
                modulo: m,
                nome: m.nome_do_motor(),
                porta,
                situacao: v.situacao,
                tentativas: v.tentativas.iter().filter(|t| agora.duration_since(**t) < JANELA_DE_TENTATIVAS).count(),
                maximo: MAX_TENTATIVAS,
                motivo: v.motivo.clone(),
                segundos: agora.duration_since(v.desde).as_secs(),
            })
        })
        .collect()
}

/// `<dados>/motores.json`: o que o serviço do Assist lê (`cicloassist/servico/conjunto.py`).
fn gravar(app: &tauri::AppHandle) {
    let Some(pasta) = pasta_dados() else { return };
    let quando = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let corpo = serde_json::json!({ "atualizado": quando, "motores": estado(app) });
    let destino = pasta.join("motores.json");
    let tmp = pasta.join("motores.json.tmp");
    if std::fs::write(&tmp, corpo.to_string()).is_ok() {
        let _ = std::fs::rename(&tmp, &destino);
    }
}

#[cfg(test)]
mod testes {
    use super::*;

    fn vigia(s: Situacao, ha: Duration, tentativas: usize) -> (Vigia, Instant) {
        let agora = Instant::now() + Duration::from_secs(3600);
        let v = Vigia { situacao: s, desde: agora - ha, tentativas: vec![agora - Duration::from_secs(5); tentativas],
                        motivo: String::new(), sem_porta_desde: None, ocupado: None };
        (v, agora)
    }

    #[test]
    fn aviso_de_ocupado_vale_so_no_prazo_e_do_proprio_filho() {
        let t = r#"{"ate": 1100, "motivo": "esperando o DaVinci Resolve (importar)", "pid": 42}"#;
        assert_eq!(ler_ocupado(t, Some(42), 1000), Some(("esperando o DaVinci Resolve (importar)".into(), 100)));
        assert_eq!(ler_ocupado(t, Some(7), 1000), None, "aviso de outro processo (um motor anterior)");
        assert_eq!(ler_ocupado(t, Some(42), 1100), None, "o prazo acabou");
        let longe = format!(r#"{{"ate": {}, "pid": 42}}"#, 1000 + TETO_OCUPADO.as_secs() + 1);
        assert_eq!(ler_ocupado(&longe, Some(42), 1000), None, "passa do teto");
        assert_eq!(ler_ocupado("não é json", Some(42), 1000), None);
    }

    #[test]
    fn subindo_dentro_do_prazo_espera() {
        let (v, agora) = vigia(Situacao::Subindo, Duration::from_secs(10), 0);
        assert_eq!(decidir(&v, false, None, agora), Acao::Nada);
    }

    #[test]
    fn subindo_alem_do_prazo_religa() {
        let (v, agora) = vigia(Situacao::Subindo, Duration::from_secs(91), 0);
        assert!(matches!(decidir(&v, false, None, agora), Acao::Religar(m) if m.contains("90 s")));
    }

    #[test]
    fn processo_que_saiu_religa_na_hora() {
        let (v, agora) = vigia(Situacao::Religando, Duration::from_secs(2), 1);
        assert!(matches!(decidir(&v, false, Some("código 1".into()), agora), Acao::Religar(m) if m.contains("código 1")));
    }

    #[test]
    fn no_ar_com_o_processo_vivo_espera_a_tolerancia() {
        let (mut v, agora) = vigia(Situacao::NoAr, Duration::from_secs(600), 0);
        v.sem_porta_desde = Some(agora - Duration::from_secs(3));
        assert_eq!(decidir(&v, false, None, agora), Acao::Nada);           // um soluço não mata o serviço
        v.sem_porta_desde = Some(agora - TOLERANCIA_SEM_PORTA);
        assert!(matches!(decidir(&v, false, None, agora), Acao::Religar(m) if m.contains("processo continua vivo")));
    }

    #[test]
    fn no_ar_cujo_processo_morreu_religa_na_hora() {
        let (v, agora) = vigia(Situacao::NoAr, Duration::from_secs(600), 0);
        assert!(matches!(decidir(&v, false, Some("código 3221225477".into()), agora),
                         Acao::Religar(m) if m.contains("o processo saiu (código 3221225477)")));
    }

    #[test]
    fn tres_tentativas_recentes_desiste() {
        let (v, agora) = vigia(Situacao::Religando, Duration::from_secs(100), MAX_TENTATIVAS);
        assert!(matches!(decidir(&v, false, None, agora), Acao::Desistir(_)));
    }

    #[test]
    fn tentativas_velhas_nao_contam() {
        let (mut v, agora) = vigia(Situacao::NoAr, Duration::from_secs(10), 0);
        v.tentativas = vec![agora - Duration::from_secs(3000); MAX_TENTATIVAS];
        v.sem_porta_desde = Some(agora - TOLERANCIA_SEM_PORTA);
        assert!(matches!(decidir(&v, false, None, agora), Acao::Religar(_)));
    }

    #[test]
    fn motor_adotado_que_sumiu_religa_na_hora() {
        // ⛔ 2026-11-07: sem filho nosso, `filho_saiu` diz como — e não se espera os 15 s / 90 s de um processo vivo.
        let quem = Some("o motor que estava na porta não era deste app".to_string());
        let (v, agora) = vigia(Situacao::NoAr, Duration::from_secs(600), 0);
        assert!(matches!(decidir(&v, false, quem.clone(), agora), Acao::Religar(m) if m.contains("não era deste app")));
        let (v, agora) = vigia(Situacao::Subindo, Duration::from_secs(2), 0);
        assert!(matches!(decidir(&v, false, quem, agora), Acao::Religar(m) if m.contains("não era deste app")));
    }

    #[test]
    fn falhou_espera_o_editor_e_subiu_e_dito() {
        let (v, agora) = vigia(Situacao::Falhou, Duration::from_secs(10), 3);
        assert_eq!(decidir(&v, false, None, agora), Acao::Nada);
        assert_eq!(decidir(&v, true, None, agora), Acao::Subiu);
    }
}
