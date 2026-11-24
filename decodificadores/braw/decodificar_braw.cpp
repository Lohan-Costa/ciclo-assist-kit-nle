// ciclo-decodificar-braw — um quadro de um clipe BRAW, em JPEG. Windows.
//
//   ciclo-decodificar-braw --file <X.braw> --frame <N> --out <out.jpg> [--max-width <W>]
//
// ⭐ Porte do `decode_braw.cpp` do RELINKER (macOS, SDK 5.1, validado lá) para o Windows,
// que é onde o serviço do Ciclo Assist roda — na mesma máquina do Media Composer.
//
// ⛔⛔ **O SDK do BRAW é OUTRO no Windows, e não é detalhe de sintaxe.** No macOS a API
// recebe `CFStringRef` e o header vem pronto; aqui:
//
//   | | macOS | Windows |
//   |---|---|---|
//   | string | `CFStringRef` | **`BSTR`** (`SysAllocString`, UTF-16) |
//   | header | `BlackmagicRawAPI.h` no SDK | **gerado do `.idl` pelo MIDL**, no build |
//   | COM | não | **`CoInitializeEx` obrigatório** antes de tudo |
//   | runtime | `BlackmagicRawAPI.framework` | `BlackmagicRawAPI.dll` + decoders |
//
// ⛔⛔ **NÃO redistribuímos o runtime.** O `CreateBlackmagicRawFactoryInstanceFromPath`
// aponta para a pasta onde ELE já está na máquina do editor, e a busca está em
// `midia/decodificadores.py` (lado Python) e em `pastasDoRuntime()` aqui. Assim a questão
// de licença nem se coloca: nada do fabricante entra no nosso pacote.
// ⭐ E no Windows do Media Composer o runtime costuma JÁ estar lá — o plugin AMA de BRAW
// do próprio Avid instala `BlackmagicRawAPI.dll` (conferido nesta máquina).
//
// ⚠️ Armadilha de ownership medida no SDK (e registrada pelo RELINKER): no `Submit()` que
// devolve S_OK **NÃO** solte o job — quem solta é o callback (`ReadComplete` solta o
// readJob, `ProcessComplete` solta o decodeJob). Soltar nos dois lugares é double-release,
// e o sintoma é um crash sem mensagem.

#include <atomic>
#include <string>
#include <vector>

#include "BlackmagicRawAPIDispatch.h"
#include "comum.h"

namespace {

// Onde o runtime do BRAW costuma estar numa máquina Windows, em ordem de preferência.
// ⚠️ A pasta do próprio executável vem primeiro: é ela que faz um dia de empacotamento
//    funcionar sem mudar código, se algum dia a licença for aceita e o runtime for junto.
std::vector<std::wstring> pastasDoRuntime() {
    std::vector<std::wstring> saida;
    std::string aqui = ciclo::exeDir();
    if (!aqui.empty()) {
        std::wstring w(aqui.begin(), aqui.end());
        saida.push_back(w);
        saida.push_back(w + L"\\BlackmagicRawAPI");
    }
    if (const wchar_t* env = _wgetenv(L"CICLOASSIST_BRAW")) saida.push_back(env);
    saida.push_back(L"C:\\Program Files (x86)\\Blackmagic Design\\Blackmagic RAW\\Blackmagic RAW SDK\\Win\\Libraries");
    // ⭐ O plugin AMA do Media Composer: quem edita BRAW no Avid já tem o runtime.
    saida.push_back(L"C:\\Program Files\\Avid\\AVX2_Plug-Ins\\AMA\\BlackmagicRAW\\BlackmagicRawAPI");
    saida.push_back(L"C:\\Program Files (x86)\\Blackmagic Design\\Blackmagic RAW\\Blackmagic RAW Player\\BlackmagicRawAPI");
    saida.push_back(L"C:\\Program Files (x86)\\Blackmagic Design\\Blackmagic RAW\\Blackmagic RAW Speed Test\\BlackmagicRawAPI");
    saida.push_back(L"C:\\Program Files\\Blackmagic Design\\DaVinci Resolve");
    return saida;
}

class Callback : public IBlackmagicRawCallback {
public:
    std::atomic<bool>    ok{false};
    std::string          erro;
    std::vector<uint8_t> rgba;
    int                  largura = 0, altura = 0;

    void STDMETHODCALLTYPE ReadComplete(IBlackmagicRawJob* readJob, HRESULT result,
                                        IBlackmagicRawFrame* frame) override {
        IBlackmagicRawJob* decode = nullptr;
        if (result == S_OK && frame) {
            frame->SetResourceFormat(blackmagicRawResourceFormatRGBAU8);
            result = frame->CreateJobDecodeAndProcessFrame(nullptr, nullptr, &decode);
            if (result == S_OK && decode) {
                if (decode->Submit() != S_OK) {
                    decode->Release();          // ⚠️ só quando o Submit FALHA.
                    erro = "o Submit do decode falhou";
                }
            } else {
                erro = "CreateJobDecodeAndProcessFrame falhou";
                if (decode) decode->Release();
            }
        } else if (erro.empty()) {
            erro = "não consegui ler o quadro do clipe";
        }
        readJob->Release();
    }

    void STDMETHODCALLTYPE ProcessComplete(IBlackmagicRawJob* job, HRESULT result,
                                           IBlackmagicRawProcessedImage* imagem) override {
        unsigned int w = 0, h = 0;
        void* dados = nullptr;
        if (result == S_OK && imagem) {
            if (imagem->GetWidth(&w) == S_OK && imagem->GetHeight(&h) == S_OK
                    && imagem->GetResource(&dados) == S_OK && dados) {
                largura = (int)w;
                altura  = (int)h;
                rgba.assign((uint8_t*)dados, (uint8_t*)dados + (size_t)w * h * 4);
                ok = true;
            } else if (erro.empty()) {
                erro = "não consegui ler os pixels do quadro processado";
            }
        } else if (erro.empty()) {
            erro = "o processamento do quadro falhou";
        }
        job->Release();
    }

    void STDMETHODCALLTYPE DecodeComplete(IBlackmagicRawJob*, HRESULT) override {}
    void STDMETHODCALLTYPE TrimProgress(IBlackmagicRawJob*, float) override {}
    void STDMETHODCALLTYPE TrimComplete(IBlackmagicRawJob*, HRESULT) override {}
    void STDMETHODCALLTYPE SidecarMetadataParseWarning(IBlackmagicRawClip*, BSTR, uint32_t, BSTR) override {}
    void STDMETHODCALLTYPE SidecarMetadataParseError(IBlackmagicRawClip*, BSTR, uint32_t, BSTR) override {}
    void STDMETHODCALLTYPE PreparePipelineComplete(void*, HRESULT) override {}

    // ⚠️ O callback vive na pilha do `main` e não é contado por referência — é o que o
    //    sample do SDK faz. Por isso AddRef/Release devolvem 0 e QueryInterface recusa.
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID, LPVOID*) override { return E_NOTIMPL; }
    ULONG   STDMETHODCALLTYPE AddRef(void) override { return 0; }
    ULONG   STDMETHODCALLTYPE Release(void) override { return 0; }
};

std::string deBstr(BSTR b) {
    if (!b) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, b, -1, nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, b, -1, &s[0], n, nullptr, nullptr);
    return s;
}

BSTR paraBstr(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    BSTR b = SysAllocStringLen(nullptr, n);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), b, n);
    return b;
}

IBlackmagicRawFactory* criarFactory(std::string& ondeAchei) {
    for (const auto& pasta : pastasDoRuntime()) {
        BSTR caminho = SysAllocString(pasta.c_str());
        IBlackmagicRawFactory* f = CreateBlackmagicRawFactoryInstanceFromPath(caminho);
        SysFreeString(caminho);
        if (f) {
            int n = WideCharToMultiByte(CP_UTF8, 0, pasta.c_str(), (int)pasta.size(),
                                        nullptr, 0, nullptr, nullptr);
            ondeAchei.resize(n);
            WideCharToMultiByte(CP_UTF8, 0, pasta.c_str(), (int)pasta.size(),
                                &ondeAchei[0], n, nullptr, nullptr);
            return f;
        }
    }
    return nullptr;
}

// ⛔⛔ **O BRAW "as shot" é LOG, e log não é o que o editor vê.** MEDIDO em 2026-09-21: o
// mesmo quadro saiu lavado pelo SDK e contrastado pelo `.mp4` que o editor converteu — céu
// branco contra céu azul. Um quadro em log faz o modelo descrever *"luz lavada, sem cor"*
// de um dia de sol, e joga o vetor de imagem para o grupo errado. ⇒ o decodificador pede
// uma gamma de VÍDEO ao SDK, e diz na saída qual conseguiu.
const wchar_t* const GAMMAS_DE_VIDEO[] = {
    L"Blackmagic Design Extended Video",
    L"Blackmagic Design Video",
    L"Rec.709",
};

// A gamma que o clipe traz, e a que se conseguiu aplicar.
struct Cor { std::string antes, depois; };

Cor ajustarGamma(IBlackmagicRawClip* clip, const std::string& pedida) {
    Cor cor;
    IBlackmagicRawClipProcessingAttributes* attrs = nullptr;
    if (clip->QueryInterface(IID_IBlackmagicRawClipProcessingAttributes, (void**)&attrs) != S_OK
            || !attrs) {
        return cor;
    }
    VARIANT v; VariantInit(&v);
    if (attrs->GetClipAttribute(blackmagicRawClipProcessingAttributeGamma, &v) == S_OK
            && v.vt == VT_BSTR) {
        cor.antes = deBstr(v.bstrVal);
    }
    VariantClear(&v);

    auto tentar = [&](const wchar_t* nome) -> bool {
        VARIANT novo; VariantInit(&novo);
        novo.vt = VT_BSTR;
        novo.bstrVal = SysAllocString(nome);
        bool deu = attrs->SetClipAttribute(blackmagicRawClipProcessingAttributeGamma, &novo) == S_OK;
        VariantClear(&novo);
        return deu;
    };

    if (!pedida.empty()) {
        std::wstring w(pedida.begin(), pedida.end());
        if (tentar(w.c_str())) cor.depois = pedida;
    } else {
        for (const wchar_t* g : GAMMAS_DE_VIDEO) {
            if (tentar(g)) { cor.depois = deBstr((BSTR)g); break; }
        }
    }
    attrs->Release();
    return cor;
}

// `--diagnostico`: o que este clipe traz e o que o SDK aceita. Não decodifica nada.
int diagnosticar(IBlackmagicRawClip* clip) {
    IBlackmagicRawClipProcessingAttributes* attrs = nullptr;
    if (clip->QueryInterface(IID_IBlackmagicRawClipProcessingAttributes,
                             (void**)&attrs) != S_OK || !attrs) {
        fprintf(stderr, "este clipe nao expoe atributos de processamento\n");
        return 1;
    }
    const struct { BlackmagicRawClipProcessingAttribute a; const char* nome; } quais[] = {
        {blackmagicRawClipProcessingAttributeColorScienceGen, "ColorScienceGen"},
        {blackmagicRawClipProcessingAttributeGamma,           "Gamma"},
        {blackmagicRawClipProcessingAttributeGamut,           "Gamut"},
    };
    for (const auto& q : quais) {
        VARIANT v; VariantInit(&v);
        if (attrs->GetClipAttribute(q.a, &v) == S_OK) {
            if (v.vt == VT_BSTR)
                printf("%-16s = %s\n", q.nome, deBstr(v.bstrVal).c_str());
            else if (v.vt == VT_UI2)
                printf("%-16s = %u\n", q.nome, (unsigned)v.uiVal);
            else if (v.vt == VT_UI4)
                printf("%-16s = %u\n", q.nome, (unsigned)v.ulVal);
            else
                printf("%-16s = (tipo %d)\n", q.nome, (int)v.vt);
        }
        VariantClear(&v);
    }

    // ⛔⛔ **`GetClipAttributeList` DERRUBA o processo** — medido em 2026-09-21 no SDK
    //    desta máquina: `0xC0000409` (stack buffer overrun), sem uma linha no stderr. Não
    //    insista: descobrir que gamma o SDK aceita sai de graça TENTANDO pôr cada uma, que
    //    é o que `ajustarGamma` já faz, e o `SetClipAttribute` responde sim ou não.
    for (const wchar_t* g : GAMMAS_DE_VIDEO) {
        VARIANT novo; VariantInit(&novo);
        novo.vt = VT_BSTR;
        novo.bstrVal = SysAllocString(g);
        HRESULT r = attrs->SetClipAttribute(blackmagicRawClipProcessingAttributeGamma, &novo);
        printf("    gamma '%s' %s\n", deBstr((BSTR)g).c_str(),
               r == S_OK ? "ACEITA" : "recusada");
        VariantClear(&novo);
    }
    attrs->Release();
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    ciclo::Args args;
    if (!parseArgs(argc, argv, args)) {
        fprintf(stderr,
                "uso: ciclo-decodificar-braw --file <X.braw> --frame <N> --out <out.jpg>"
                " [--max-width <W>] [--gamma <nome>]\n"
                "     ciclo-decodificar-braw --file <X.braw> --diagnostico\n");
        return 2;
    }

    // ⛔ COM primeiro: sem isto a factory devolve nulo e o motivo não aparece em lugar nenhum.
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) { fprintf(stderr, "CoInitializeEx falhou (0x%08lx)\n", (unsigned long)hr); return 3; }

    std::string ondeAchei;
    IBlackmagicRawFactory* factory = criarFactory(ondeAchei);
    if (!factory) {
        fprintf(stderr,
                "não achei o runtime do Blackmagic RAW nesta máquina. Instale o Blackmagic"
                " RAW SDK (ou o Blackmagic RAW Player), ou aponte a pasta que tem o"
                " BlackmagicRawAPI.dll em CICLOASSIST_BRAW.\n");
        CoUninitialize();
        return 4;
    }

    IBlackmagicRaw*        codec   = nullptr;
    IBlackmagicRawClip*    clip    = nullptr;
    IBlackmagicRawJob*     leitura = nullptr;
    Callback               cb;
    int                    saida   = 1;

    do {
        if (factory->CreateCodec(&codec) != S_OK || !codec) {
            fprintf(stderr, "não consegui criar o codec do BRAW (runtime em %s)\n",
                    ondeAchei.c_str());
            break;
        }
        BSTR arquivo = paraBstr(args.file);
        HRESULT r = codec->OpenClip(arquivo, &clip);
        SysFreeString(arquivo);
        if (r != S_OK || !clip) {
            fprintf(stderr, "não consegui abrir %s como clipe BRAW\n", args.file.c_str());
            break;
        }
        if (args.diagnostico) {
            saida = diagnosticar(clip);
            break;
        }
        // ⛔ A gamma ANTES de pedir o quadro: o atributo é do CLIPE, e o job de decode já
        //    sai com o que estiver valendo.
        Cor cor = ajustarGamma(clip, args.gamma);
        if (cor.depois.empty() && !cor.antes.empty()) {
            // ⚠️ Não é erro: o quadro sai em log, e quem lê o stderr fica sabendo por quê.
            fprintf(stderr,
                    "aviso: não consegui aplicar gamma de vídeo (o clipe está em '%s');"
                    " o quadro sai como foi gravado\n", cor.antes.c_str());
        }
        if (codec->SetCallback(&cb) != S_OK) {
            fprintf(stderr, "não consegui registrar o callback do SDK\n");
            break;
        }
        // ⚠️ `CreateJobReadFrame` recebe o ÍNDICE do quadro no clipe (0-based), e não
        //    tempo: quem converte timecode em quadro é o Python (`frames.py`).
        if (clip->CreateJobReadFrame((long)args.frame, &leitura) != S_OK || !leitura) {
            fprintf(stderr, "não consegui pedir o quadro %d\n", args.frame);
            break;
        }
        if (leitura->Submit() != S_OK) {
            leitura->Release();               // ⚠️ só quando o Submit FALHA.
            leitura = nullptr;
            fprintf(stderr, "o Submit da leitura falhou\n");
            break;
        }
        leitura = nullptr;                    // ⛔ a partir daqui o callback é o dono.
        codec->FlushJobs();                   // síncrono: volta com o trabalho feito.

        if (!cb.ok) {
            fprintf(stderr, "%s\n", cb.erro.empty() ? "o SDK não devolveu o quadro"
                                                    : cb.erro.c_str());
            break;
        }
        if (!ciclo::writeJpeg(args.out, cb.rgba.data(), cb.largura, cb.altura,
                              4, /*bgr=*/false, args.maxWidth)) {
            break;
        }
        saida = 0;
    } while (false);

    if (leitura) leitura->Release();
    if (clip)    clip->Release();
    if (codec)   codec->Release();
    factory->Release();
    CoUninitialize();
    return saida;
}
