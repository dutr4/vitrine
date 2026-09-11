#!/usr/bin/env python3
"""Coletor de ofertas da Amazon para a vitrine.

Modo 1 (deals): varre a pagina /deals e extrai os cards do JSON embutido
                (preco, "De:", selo de desconto, estado da oferta).
Modo 2 (asins): para uma lista de ASINs, busca a pagina do produto e extrai
                titulo, preco, preco de referencia, disponibilidade, imagem,
                avaliacao e cupom ativo.

Saida: JSON com as ofertas normalizadas + timestamp de verificacao.

Uso:
  python3 coletar_ofertas.py deals  saida.json
  python3 coletar_ofertas.py asins  saida.json ASIN1 ASIN2 ...
  python3 coletar_ofertas.py asins-arquivo saida.json lista.txt
"""
from __future__ import annotations

import html as htmllib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TZ_BR = timezone(timedelta(hours=-3))

DEALS_URL = "https://www.amazon.com.br/deals"
PRODUTO_URL = "https://www.amazon.com.br/dp/{asin}"


UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def baixar(url: str, tentativas: int = 3, mobile: bool = False) -> str:
    """Baixa uma URL com curl (--compressed) e retorna o HTML. Retenta em 503."""
    ua = UA_MOBILE if mobile else UA
    for t in range(tentativas):
        proc = subprocess.run(
            [
                "curl", "-s", "-m", "30", "--compressed", "-L",
                "-H", f"User-Agent: {ua}",
                "-H", "Accept-Language: pt-BR,pt;q=0.9,en;q=0.8",
                "-H", "Accept: text/html,application/xhtml+xml",
                "-w", "\n__HTTP__%{http_code}",
                url,
            ],
            capture_output=True,
        )
        corpo = proc.stdout.decode("utf-8", errors="replace")
        m = re.search(r"__HTTP__(\d+)$", corpo)
        codigo = int(m.group(1)) if m else 0
        corpo = re.sub(r"\n__HTTP__\d+$", "", corpo)
        if codigo == 200 and len(corpo) > 20000:
            return corpo
        time.sleep(3 + 3 * t)
    return ""


# ---------------------------------------------------------------- modo deals
def cards_deals(html: str) -> list[dict]:
    """Extrai os cards JSON embutidos na pagina /deals."""
    ofertas = []
    for m in re.finditer(r'\{"asin":"([A-Z0-9]{10})","title":', html):
        bloco = html[m.start(): m.start() + 6000]
        if '"priceToPay"' not in bloco:
            continue

        def campo(pat, src=bloco):
            mm = re.search(pat, src)
            return mm.group(1) if mm else None

        titulo = campo(r'"title":"([^"]*)"')
        preco = campo(r'"priceToPay":\{[^}]*"price":"([\d.]+)"')
        de = campo(r'"basisPrice":\{[^}]*"price":"([\d.]+)"')
        if not (titulo and preco):
            continue

        asin = m.group(1)
        img = campo(r'"hiRes":\{"baseUrl":"([^"]*)"')
        ext = campo(r'"hiRes":\{"baseUrl":"[^"]*","extension":"([^"]*)"')
        ofertas.append({
            "asin": asin,
            "titulo": htmllib.unescape(titulo),
            "preco": round(float(preco), 2),
            "preco_referencia": round(float(de), 2) if de else None,
            "selo_desconto": campo(r'"dealBadge":\{"label":\{"content":\{"fragments":\[\{"text":"([^"]*)"'),
            "selo_texto": campo(r'"messaging":\{"content":\{"fragments":\[\{"text":"([^"]*)"'),
            "estado_oferta": campo(r'"dealDetails":\{"state":"([^"]*)"'),
            "lightning": campo(r'"isLightningDeal":(true|false)') == "true",
            "imagem": f"{img}.{ext}" if img and ext else None,
            "fonte": "deals",
        })

    unicos, vistos = [], set()
    for o in ofertas:
        if o["asin"] in vistos:
            continue
        vistos.add(o["asin"])
        unicos.append(o)
    return unicos


# -------------------------------------------------------- modo busca (resultados)
_RE_ASIN_ANTES = re.compile(r'data-asin="([A-Z0-9]{10})"')


def _preco_br(txt: str) -> float | None:
    """Converte '1.299,90' -> 1299.90"""
    if not txt:
        return None
    t = re.sub(r"[^\d,\.]", "", txt).strip().replace(".", "").replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def cards_busca(html: str) -> list[dict]:
    """Extrai os cards de uma pagina de resultados de busca (server-rendered)."""
    marcas = [m.start() for m in re.finditer(r'data-component-type="s-search-result"', html)]
    ofertas = []
    for i, pos in enumerate(marcas):
        fim = marcas[i + 1] if i + 1 < len(marcas) else min(len(html), pos + 16000)
        cabeca = html[max(0, pos - 600):pos]
        m_asin = _RE_ASIN_ANTES.search(cabeca[::-1][::-1]) or _RE_ASIN_ANTES.search(cabeca)
        if not m_asin:
            continue
        bloco = html[pos:fim]

        m_tit = (re.search(r'<h2[^>]*>(?:<span[^>]*>)?([^<]{5,300})', bloco)
                 or re.search(r'aria-label="([^"]{5,300})"', bloco))
        # Preco principal = primeiro span class="a-price" (exato, sem a-text-price).
        # Parcelamento e preco riscado usam a-text-price e nao entram aqui.
        m_preco = re.search(
            r'class="a-price"[^>]*>(?:(?!class="a-price").){0,300}?a-offscreen">\s*R\$\s*([\d\.]+,?\d*)',
            bloco, re.S,
        )
        preco = _preco_br(m_preco.group(1)) if m_preco else None
        if not preco:
            cands = [_preco_br(p) for p in re.findall(r'a-offscreen">\s*R\$\s*([\d\.]+,?\d*)', bloco)]
            cands = [c for c in cands if c]
            preco = min(cands) if cands else None
        if not preco:
            continue

        # Preco de referencia ("De:") = span com data-a-strike="true"
        m_strike = re.search(
            r'data-a-strike="true"[^>]*>(?:(?!</span>\s*</span>).){0,300}?a-offscreen">\s*R\$\s*([\d\.]+,?\d*)',
            bloco, re.S,
        )
        referencia = _preco_br(m_strike.group(1)) if m_strike else None
        if referencia and preco and referencia <= preco:
            referencia = None

        m_est = re.search(r'([\d,]{1,3})\s*de\s*5\s*estrelas', bloco)
        m_ava = re.search(r's-underline-text[^>]*>\s*\(?([\d\.]+)\)?', bloco)
        m_img = re.search(r'class="s-image"[^>]*src="([^"]+)"', bloco)
        patrocinado = ("AdHolder" in bloco) or ("Patrocinado" in bloco)

        ofertas.append({
            "asin": m_asin.group(1),
            "titulo": htmllib.unescape(m_tit.group(1)).strip() if m_tit else None,
            "preco": preco,
            "preco_referencia": referencia,
            "estrelas": float(m_est.group(1).replace(",", ".")) if m_est else None,
            "avaliacoes": int(m_ava.group(1).replace(".", "")) if m_ava else None,
            "imagem": m_img.group(1) if m_img else None,
            "patrocinado": patrocinado,
            "fonte": "busca",
        })

    unicos, vistos = [], set()
    for o in ofertas:
        if o["asin"] in vistos or not o["titulo"]:
            continue
        vistos.add(o["asin"])
        unicos.append(o)
    return unicos


# -------------------------------------------------------- modo pagina produto
_RE_TITULO = re.compile(r'<span id="productTitle"[^>]*>\s*([^<]+)', re.S)
_RE_OG_TITULO = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')
_RE_OG_IMG = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
_RE_PRICE_OFFSCREEN = re.compile(r'class="a-offscreen">\s*R\$\s*([\d\.]+,?\d*)')
_RE_PRECO_MOBILE = re.compile(
    r'id="apex-pricetopay-accessibility-label"[^>]*>\s*R\$\s*([\d\.]+,?\d*)'
)
_RE_ADD_CART = re.compile(r'name="submit\.add-to-cart"|id="add-to-cart-button"')
_RE_ESTRELAS = re.compile(r'([\d,]{1,3})\s*de\s*5\s*estrelas')
# Avaliacoes: escopar no bloco canonico (fora dele vem numero de outro produto)
_RE_AVALIACOES = re.compile(r'([\d\.]+)\s*avalia[çc][õo]es')
_RE_AVALIACOES_ESCOPO = re.compile(
    r'averageCustomerReviews_feature_div.(0, 600)?([\d\.]+)\s*avalia[çc][õo]es', re.S
)
_RE_INDISPONIVEL = re.compile(
    r"Temporariamente fora de estoque|No momento, este item n[ãa]o est[áa] dispon[íi]vel|"
    r"Atualmente indispon[íi]vel|Currently unavailable",
    re.I,
)


def _preco_br(txt: str) -> float | None:
    """Converte '1.299,90' -> 1299.90"""
    if not txt:
        return None
    t = txt.strip().replace(".", "").replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def info_produto(asin: str) -> dict | None:
    """Busca e parseia a pagina do produto (UA mobile = preco no HTML estatico)."""
    html = baixar(PRODUTO_URL.format(asin=asin), mobile=True)
    if not html:
        return None

    m = _RE_TITULO.search(html) or _RE_OG_TITULO.search(html)
    titulo = htmllib.unescape(m.group(1)).strip() if m else None
    if not titulo:
        mt = re.search(r"<title>([^<]+)</title>", html)
        titulo = htmllib.unescape(mt.group(1)).split(" : ")[0].strip() if mt else None
    if not titulo:
        return None

    # PRECO: apenas fontes escopadas e inequivocas.
    # NUNCA usar "menor preco da pagina": paginas degradadas/bloqueadas misturam
    # precos de acessorios e produtos relacionados, e isso ja produziu preco errado.
    preco = None
    m_p = _RE_PRECO_MOBILE.search(html)          # label de acessibilidade do bloco apex
    if m_p:
        preco = _preco_br(m_p.group(1))
    if preco is None:
        m_p = re.search(r'id="price_inside_buybox"[^>]*>\s*R\$\s*([\d\.]+,?\d*)', html)
        if m_p:
            preco = _preco_br(m_p.group(1))
    if preco is None:
        m_p = re.search(
            r'id="buybox"[^>]*>(?:(?!id="buybox").){0,4000}?class="a-offscreen">\s*R\$\s*([\d\.]+,?\d*)',
            html, re.S,
        )
        if m_p:
            preco = _preco_br(m_p.group(1))

    # preco de referencia (riscado), quando existir
    m_r = re.search(
        r'data-a-strike="true"[^>]*>(?:(?!</span>\s*</span>).){0,400}?a-offscreen">\s*R\$\s*([\d\.]+,?\d*)',
        html, re.S,
    )
    if not m_r:
        m_r = re.search(
            r'a-text-price[^>]*>(?:(?!</span>\s*</span>).){0,400}?a-offscreen">\s*R\$\s*([\d\.]+,?\d*)',
            html, re.S,
        )
    referencia = _preco_br(m_r.group(1)) if m_r else None
    if referencia and preco and referencia <= preco:
        referencia = None

    estrelas = _RE_ESTRELAS.search(html)
    avaliacoes = _RE_AVALIACOES_ESCOPO.search(html) or _RE_AVALIACOES.search(html)

    # imagem: JSON mobile-landing-image-data; fallback no <img> grande
    m_img = (re.search(r'"landingImageUrl":"([^"]+)"', html)
             or re.search(r'<img[^>]+src="(https://m\.media-amazon\.com/images/I/[^"]+)"', html)
             or _RE_OG_IMG.search(html))
    imagem = m_img.group(1) if m_img else None
    if imagem:
        # padroniza para 500px (as URLs mobile vem em 350px)
        imagem = re.sub(r"_AC_UF\d+,\d+_QL\d+_", "_AC_UF500,500_QL80_", imagem)
        imagem = re.sub(r"\._AC_[A-Z0-9,_]+_\.", "._AC_UF500,500_QL80_.", imagem)

    # DISPONIBILIDADE: exige indicio positivo e escopado (evita marcar como
    # indisponivel so porque a pagina veio degradada).
    indisponivel = bool(_RE_INDISPONIVEL.search(html))
    tem_botao = bool(_RE_ADD_CART.search(html))
    disponivel = tem_botao and not indisponivel
    if not preco and not indisponivel:
        # pagina sem preco e sem aviso de indisponibilidade: leitura nao confiavel
        indisponivel = False
        disponivel = False
        motivo = "leituras ausentes (pagina degradada?)"
    else:
        motivo = None if disponivel else ("sem botao de compra" if not indisponivel else "fora de estoque")

    return {
        "asin": asin,
        "titulo": titulo,
        "preco": preco,
        "preco_referencia": referencia,
        "disponivel": disponivel,
        "indisponivel_motivo": motivo,
        "estrelas": float(estrelas.group(1).replace(",", ".")) if estrelas else None,
        "avaliacoes": int(avaliacoes.group(1).replace(".", "")) if avaliacoes else None,
        "imagem": imagem,
        "fonte": "produto",
    }



# ------------------------------------------------- leitura em lote (navegador)
def info_produtos_lote(asins: list[str], container: str | None = None) -> dict[str, dict]:
    """Le varias paginas de produto com navegador real (Playwright) rodando dentro
    de um container. A Amazon passou a servir pagina degradada (sem preco) para
    clientes que nao sao navegador, entao este e o caminho confiavel.

    Devolve {asin: info} no mesmo formato de info_produto(). Retorna {} quando
    indisponivel (sem docker/container), e o chamador cai no fallback por curl.
    """
    if not asins or os.environ.get("VITRINE_PW_DISABLED") == "1":
        return {}
    container = container or os.environ.get("VITRINE_PW_CONTAINER", "promobot-dev-promobot-1")

    checa = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True, text=True,
    )
    if checa.returncode != 0 or "true" not in checa.stdout.lower():
        return {}

    base = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["docker", "cp", os.path.join(base, "pw_reader.py"), f"{container}:/tmp/pw_reader.py"],
                   capture_output=True, text=True)

    resultados: dict[str, dict] = {}
    lote = 8  # lotes menores: menos risco de timeout e de bloqueio
    for i in range(0, len(asins), lote):
        proc = subprocess.run(
            ["docker", "exec", container, "python", "/tmp/pw_reader.py", *asins[i:i + lote]],
            capture_output=True, text=True, timeout=900,
        )
        for linha in (proc.stdout or "").splitlines():
            try:
                d = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if not d.get("asin"):
                continue
            resultados[d["asin"]] = {
                "asin": d["asin"],
                "titulo": d.get("titulo"),
                "preco": d.get("preco"),
                "preco_referencia": d.get("preco_referencia"),
                "disponivel": bool(d.get("disponivel")),
                "indisponivel_motivo": None if d.get("disponivel") else (d.get("motivo") or "sem compra"),
                "estrelas": d.get("estrelas"),
                "avaliacoes": d.get("avaliacoes"),
                "imagem": d.get("imagem"),
                "fonte": "playwright",
            }
    return resultados


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    modo, saida = sys.argv[1], sys.argv[2]
    if modo == "deals":
        html = baixar(DEALS_URL)
        ofertas = cards_deals(html) if html else []
    elif modo == "busca":
        termos = sys.argv[3:]
        ofertas = []
        for i, termo in enumerate(termos, 1):
            url = f"https://www.amazon.com.br/s?k={quote_plus(termo)}"
            html = baixar(url)
            cards = cards_busca(html) if html else []
            print(f"  [{i}/{len(termos)}] '{termo}': {len(cards)} cards", file=sys.stderr)
            ofertas.extend(cards)
            time.sleep(3)
    elif modo == "asins":
        asins = sys.argv[3:]
        ofertas = []
        for i, a in enumerate(asins, 1):
            info = info_produto(a)
            print(f"  [{i}/{len(asins)}] {a}: {'ok' if info else 'FALHOU'}", file=sys.stderr)
            if info:
                ofertas.append(info)
            time.sleep(2.5)
    elif modo == "asins-arquivo":
        asins = [l.strip() for l in open(sys.argv[3]) if l.strip() and not l.startswith("#")]
        ofertas = []
        for i, a in enumerate(asins, 1):
            info = info_produto(a)
            print(f"  [{i}/{len(asins)}] {a}: {'ok' if info else 'FALHOU'}", file=sys.stderr)
            if info:
                ofertas.append(info)
            time.sleep(2.5)
    else:
        print(f"modo desconhecido: {modo}")
        sys.exit(1)

    dados = {
        "coletado_em": datetime.now(TZ_BR).isoformat(timespec="seconds"),
        "total": len(ofertas),
        "ofertas": ofertas,
    }
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"salvo: {saida} ({len(ofertas)} ofertas)")


if __name__ == "__main__":
    main()
