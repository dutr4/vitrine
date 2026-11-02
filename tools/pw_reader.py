#!/usr/bin/env python3
"""Leitor de páginas de produto da Amazon com navegador real (Playwright).

Roda DENTRO de um container que tenha Playwright instalado (ex.: o do PromoBot).
Recebe ASINs por argumento e imprime um JSON por linha (um por ASIN) em stdout.

Uso: python pw_reader.py ASIN1 ASIN2 ...
Saída (uma linha por ASIN):
  {"asin": "...", "titulo": "...", "preco": 123.45, "preco_referencia": null,
   "desconto": "-12%", "disponivel": true, "motivo": null, "estrelas": 4.6,
   "avaliacoes": null, "imagem": "https://..."}
"""
from __future__ import annotations

import json
import os
import random
import re
import sys

from playwright.sync_api import sync_playwright

TAG = "dutr4oferta00-20"

# A Amazon bloqueia por fingerprint de cliente, nao so por IP: o UA padrao do
# Playwright ("HeadlessChrome") e o primeiro sinal. Com UA real + ritmo humano a
# leitura passa; sem isso 40 de 50 paginas voltam sem titulo (02/11/2026).
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PAUSA_PAGINA = float(os.environ.get("VITRINE_PAUSA_PAGINA", "8"))   # entre ASINs
TENTATIVAS = int(os.environ.get("VITRINE_PW_TENTATIVAS", "2"))


def limpa(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def normaliza(t):
    """Remove espaços que a Amazon insere no meio dos números ('R$698 , 17')."""
    return re.sub(r"(\d)\s*,\s*(\d{2})", r"\1,\2", t or "")


def valor(t):
    m = re.search(r"R\$\s?([\d\.]+),(\d{2})", t or "")
    return float(f"{m.group(1).replace('.', '')}.{m.group(2)}") if m else None


def ler(pg, asin):
    d = {"asin": asin, "titulo": None, "preco": None, "preco_referencia": None,
         "desconto": None, "disponivel": False, "motivo": None, "estrelas": None,
         "avaliacoes": None, "imagem": None}
    # wait_until="commit" + espera pelo BLOCO DO PRODUTO: a Amazon as vezes entrega
    # so o cabecalho (pagina degradada) e "domcontentloaded" fica pendurado em
    # assets lentos. Esperar o seletor e deterministico; esperar 2s no relogio nao.
    pg.goto(f"https://www.amazon.com.br/dp/{asin}?tag={TAG}", wait_until="commit", timeout=60000)
    try:
        pg.wait_for_selector(
            "#productTitle, #corePriceDisplay_desktop_feature_div, #outOfStock",
            timeout=25000,
        )
    except Exception:  # noqa: BLE001
        pass  # segue: o chamador trata "sem titulo" como leitura nao confiavel
    pg.wait_for_timeout(700)

    el = pg.query_selector("#productTitle")
    d["titulo"] = limpa(el.inner_text()) if el else None
    if not d["titulo"]:
        corpo = ""
        try:
            corpo = pg.content()
        except Exception:  # noqa: BLE001
            pass
        if re.search(r"Digite os caracteres|Introduza os caracteres|nao e um robo|"
                     r"não é um robô|api-services-support|validateCaptcha", corpo, re.I):
            d["motivo"] = "captcha/bloqueio"
        elif not corpo:
            d["motivo"] = "pagina vazia"
        else:
            d["motivo"] = "pagina sem titulo"
        return d

    blocos = []
    for sel in ("#corePriceDisplay_desktop_feature_div", "#apex_desktop", "#buybox", "#price_inside_buybox"):
        e = pg.query_selector(sel)
        if e:
            blocos.append(normaliza(limpa(e.inner_text())))
    texto = " ".join(blocos)
    # Layout real do bloco: "R$ 698,17 com 19 por cento de desconto -19% R$698 , 17
    # De: R$ 865,56 ..." -> o PRIMEIRO valor é o preço a pagar e o riscado vem
    # ancorado em "De:". Não dependemos da ordem relativa dos dois.
    d["preco"] = valor(texto)
    m = re.search(r"De:?\s*(R\$\s?[\d\.]+,\d{2})", texto)
    d["preco_referencia"] = valor(m.group(1)) if m else None
    if d["preco_referencia"] and d["preco"] and d["preco_referencia"] <= d["preco"]:
        d["preco_referencia"] = None

    mp = pg.query_selector("#corePriceDisplay_desktop_feature_div .savingsPercentage")
    d["desconto"] = limpa(mp.inner_text()) if mp else None

    el = pg.query_selector("#availability") or pg.query_selector("#outOfStock")
    disp = limpa(el.inner_text()) if el else ""
    # Aviso explicito de indisponibilidade e o unico sinal que reprova a oferta.
    # "Compra única" / outros vendedores NAO significa indisponivel: o botao de
    # compra continua ativo no anuncio em destaque.
    fora = bool(re.search(r"indispon|fora de estoque", disp, re.I))
    compra = pg.query_selector("#add-to-cart-button") is not None
    d["disponivel"] = bool(compra) and not fora
    if not d["disponivel"]:
        d["motivo"] = f"sem botao de compra (availability={disp[:40]!r})" if not fora else "fora de estoque"
    elif not d["preco"]:
        d["disponivel"] = False
        d["motivo"] = "sem preco legivel"

    m = pg.query_selector("#acrPopover")
    if m:
        t = m.get_attribute("title") or ""
        mm = re.search(r"([\d,]+)\s*de\s*5", t)
        if mm:
            d["estrelas"] = float(mm.group(1).replace(",", "."))
    m = pg.query_selector("#acrCustomerReviewText")
    if m:
        mm = re.search(r"([\d\.]+)", limpa(m.inner_text()))
        if mm:
            d["avaliacoes"] = int(mm.group(1).replace(".", ""))
    m = pg.query_selector("#landingImage")
    if m:
        d["imagem"] = m.get_attribute("src")
    return d


def main():
    asins = [a for a in sys.argv[1:] if a]
    with sync_playwright() as p:
        nav = p.chromium.launch(args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ])
        try:
            _ler_lote(nav, asins)
        finally:
            # Sem o finally, um exec interrompido deixa o Chromium vivo dentro do
            # container; somado aos zumbis (PID 1 nao colhe filhos de docker exec)
            # a rodada seguinte morre com "TargetClosedError: Page crashed".
            try:
                nav.close()
            except Exception:  # noqa: BLE001
                pass


def _ler_lote(nav, asins):
    ctx = nav.new_context(
        user_agent=UA,
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        viewport={"width": 1366, "height": 768},
        extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
    )
    # Esconde o "webdriver" que o Chromium anuncia por padrao.
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    pg = ctx.new_page()
    # Aquecimento: uma visita a home por processo deixa cookies de visitante.
    try:
        pg.goto("https://www.amazon.com.br/", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
    except Exception:  # noqa: BLE001
        pass

    for i, a in enumerate(asins):
        d = None
        for tentativa in range(1, TENTATIVAS + 1):
            try:
                d = ler(pg, a)
            except Exception as e:  # noqa: BLE001
                d = {"asin": a, "titulo": None, "preco": None, "disponivel": False,
                     "motivo": f"erro: {type(e).__name__}"}
            if d.get("titulo"):
                break
            if tentativa < TENTATIVAS:
                # Bloqueio costuma ser passageiro: espera e tenta de novo.
                pg.wait_for_timeout(8000 + random.randint(0, 5000))
        print(json.dumps(d, ensure_ascii=False), flush=True)
        if i + 1 < len(asins):
            pg.wait_for_timeout(int(PAUSA_PAGINA * 1000) + random.randint(0, 2500))


if __name__ == "__main__":
    main()
