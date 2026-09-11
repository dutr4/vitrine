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
import re
import sys

from playwright.sync_api import sync_playwright

TAG = "dutr4ofertas-20"


def limpa(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def valor(t):
    m = re.search(r"R\$\s?([\d\.]+),(\d{2})", t or "")
    return float(f"{m.group(1).replace('.', '')}.{m.group(2)}") if m else None


def ler(pg, asin):
    d = {"asin": asin, "titulo": None, "preco": None, "preco_referencia": None,
         "desconto": None, "disponivel": False, "motivo": None, "estrelas": None,
         "avaliacoes": None, "imagem": None}
    pg.goto(f"https://www.amazon.com.br/dp/{asin}?tag={TAG}", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(2200)

    el = pg.query_selector("#productTitle")
    d["titulo"] = limpa(el.inner_text()) if el else None
    if not d["titulo"]:
        d["motivo"] = "pagina sem titulo"
        return d

    blocos = []
    for sel in ("#corePriceDisplay_desktop_feature_div", "#apex_desktop", "#buybox", "#price_inside_buybox"):
        e = pg.query_selector(sel)
        if e:
            blocos.append(limpa(e.inner_text()))
    texto = " ".join(blocos)
    d["preco"] = valor(texto) or (valor(blocos[0]) if blocos else None)

    # preço riscado ("De:") dentro do bloco de preço
    m = re.search(r"(?:De|de:?)\s*(R\$\s?[\d\.]+,\d{2}).*?(?:R\$\s?[\d\.]+,\d{2})", texto)
    if m:
        d["preco_referencia"] = valor(m.group(1))
    if d["preco_referencia"] and d["preco"] and d["preco_referencia"] <= d["preco"]:
        d["preco_referencia"] = None

    mp = pg.query_selector("#corePriceDisplay_desktop_feature_div .savingsPercentage")
    d["desconto"] = limpa(mp.inner_text()) if mp else None

    el = pg.query_selector("#availability") or pg.query_selector("#outOfStock")
    disp = limpa(el.inner_text()) if el else ""
    compra = pg.query_selector("#add-to-cart-button") is not None
    terceiros = pg.query_selector("#buybox-see-all-buying-choices") is not None
    d["disponivel"] = bool(compra) and not terceiros
    if not d["disponivel"]:
        d["motivo"] = f"sem botao de compra (availability={disp[:40]!r})"
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
        nav = p.chromium.launch(args=["--no-sandbox"])
        pg = nav.new_page(locale="pt-BR")
        for a in asins:
            try:
                print(json.dumps(ler(pg, a), ensure_ascii=False), flush=True)
            except Exception as e:  # noqa: BLE001
                print(json.dumps({"asin": a, "titulo": None, "preco": None, "disponivel": False,
                                  "motivo": f"erro: {type(e).__name__}"}, ensure_ascii=False), flush=True)
        nav.close()


if __name__ == "__main__":
    main()
