// O que todo decodificador de RAW de câmera compartilha: argumentos, JPEG e o caminho do
// próprio executável.
//
// ⭐⭐ **O contrato é o do RELINKER** (`docs/raw-decoders.md` de lá), e é de propósito: os
// dois apps da casa falam a mesma língua, e um helper construído para um serve ao outro.
//
//   ciclo-decodificar-<tipo> --file <X> --frame <N> --out <out.jpg> [--max-width <W>]
//       exit 0  → gravou out.jpg        exit ≠0 → motivo no stderr
//
// ⛔ **Binário externo, e não um binding.** Três razões, todas do RELINKER e todas boas:
//   1. licença isolada — o código do fabricante não entra no nosso pacote;
//   2. um decode que quebra não derruba o serviço (e com isso o painel do editor);
//   3. o build é por plataforma, e fica isolado num lugar só.
//
// ⚠️ Este header DEFINE as implementações do stb: inclua-o em UM .cpp por binário.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#ifdef _WIN32
#  include <windows.h>
#else
#  include <mach-o/dyld.h>
#endif

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "stb_image_resize2.h"

namespace ciclo {

struct Args {
    std::string file;
    int         frame    = 0;
    std::string out;
    // ⚠️ O padrão é o `frames.LARGURA` do produto (768 px). Ele não é economia de disco:
    //    é o que cabe na janela do modelo sem estourar contexto — ver `midia/frames.py`.
    int         maxWidth = 768;
    // ⚠️ Vazio = o decodificador escolhe (ver `GAMMAS_DE_VIDEO`). Só o BRAW usa.
    std::string gamma;
    // Não decodifica: imprime o que o clipe traz e o que o SDK aceita.
    bool        diagnostico = false;
};

inline bool parseArgs(int argc, char** argv, Args& a) {
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        auto next = [&](const char* what) -> const char* {
            if (i + 1 >= argc) { fprintf(stderr, "faltou valor para %s\n", what); return nullptr; }
            return argv[++i];
        };
        if (k == "--file")           { auto v = next("--file");      if (!v) return false; a.file = v; }
        else if (k == "--frame")     { auto v = next("--frame");     if (!v) return false; a.frame = atoi(v); }
        else if (k == "--out")       { auto v = next("--out");       if (!v) return false; a.out = v; }
        else if (k == "--max-width") { auto v = next("--max-width"); if (!v) return false; a.maxWidth = atoi(v); }
        else if (k == "--gamma")     { auto v = next("--gamma");     if (!v) return false; a.gamma = v; }
        else if (k == "--diagnostico") { a.diagnostico = true; }
        else { fprintf(stderr, "argumento desconhecido: %s\n", k.c_str()); return false; }
    }
    return !a.file.empty() && (a.diagnostico || !a.out.empty());
}

// Pixels interleaved (3 ou 4 canais) → JPEG, reduzido para `maxWidth` mantendo a
// proporção. `bgr` troca R↔B (buffers BGRA de alguns SDKs).
inline bool writeJpeg(const std::string& out, const uint8_t* pix, int w, int h,
                      int channels, bool bgr, int maxWidth, int quality = 90) {
    if (w <= 0 || h <= 0) { fprintf(stderr, "quadro sem tamanho (%dx%d)\n", w, h); return false; }
    std::vector<uint8_t> rgb((size_t)w * h * 3);
    const int rIdx = bgr ? 2 : 0, bIdx = bgr ? 0 : 2;
    for (size_t i = 0, n = (size_t)w * h; i < n; ++i) {
        rgb[i * 3 + 0] = pix[i * channels + rIdx];
        rgb[i * 3 + 1] = pix[i * channels + 1];
        rgb[i * 3 + 2] = pix[i * channels + bIdx];
    }
    const uint8_t* src = rgb.data();
    int ow = w, oh = h;
    std::vector<uint8_t> menor;
    if (maxWidth > 0 && w > maxWidth) {
        ow = maxWidth;
        oh = (int)((int64_t)h * maxWidth / w);
        if (oh < 1) oh = 1;
        menor.resize((size_t)ow * oh * 3);
        if (!stbir_resize_uint8_srgb(rgb.data(), w, h, 0, menor.data(), ow, oh, 0, STBIR_RGB)) {
            fprintf(stderr, "falha ao redimensionar\n");
            return false;
        }
        src = menor.data();
    }
    if (!stbi_write_jpg(out.c_str(), ow, oh, 3, src, quality)) {
        fprintf(stderr, "falha ao gravar JPEG: %s\n", out.c_str());
        return false;
    }
    return true;
}

// A pasta do próprio executável — o primeiro lugar onde se procura o runtime do SDK.
inline std::string exeDir() {
#ifdef _WIN32
    char buf[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, buf, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return "";
    std::string p(buf, n);
    auto barra = p.find_last_of("\\/");
    return barra == std::string::npos ? "" : p.substr(0, barra);
#else
    char buf[4096]; uint32_t sz = sizeof(buf);
    if (_NSGetExecutablePath(buf, &sz) != 0) return "";
    std::string p(buf);
    auto barra = p.find_last_of('/');
    return barra == std::string::npos ? "" : p.substr(0, barra);
#endif
}

} // namespace ciclo
