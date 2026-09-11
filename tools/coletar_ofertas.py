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

    # preco principal: label de acessibilidade do bloco apex (mobile)
    m_p = _RE_PRECO_MOBILE.search(html)
    preco = _preco_br(m_p.group(1)) if m_p else None
    if preco is None:
        cands = [_preco_br(p) for p in _RE_PRICE_OFFSCREEN.findall(html)]
        cands = [c for c in cands if c]
        preco = min(cands) if cands else None

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

    indisponivel = bool(_RE_INDISPONIVEL.search(html))
    tem_botao = bool(_RE_ADD_CART.search(html))
    disponivel = tem_botao and not indisponivel

    return {
        "asin": asin,
        "titulo": titulo,
        "preco": preco,
        "preco_referencia": referencia,
        "disponivel": disponivel,
        "indisponivel_motivo": (None if disponivel else ("sem botao de compra" if not indisponivel else "fora de estoque")),
        "estrelas": float(estrelas.group(1).replace(",", ".")) if estrelas else None,
        "avaliacoes": int(avaliacoes.group(1).replace(".", "")) if avaliacoes else None,
        "imagem": imagem,
        "fonte": "produto",
    }


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
