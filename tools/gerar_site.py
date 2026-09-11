#!/usr/bin/env python3
"""Gera a secao de ofertas da vitrine a partir de dados/ofertas.json.

Le dados/ofertas.json (ofertas verificadas), monta o HTML da vitrine agrupado
por categoria e substitui o bloco entre os marcadores OFERTAS:INICIO/FIM do
index.html. Tambem atualiza os marcadores de data/preco verificados.

Uso: python3 tools/gerar_site.py [--dry-run]
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "dados", "ofertas.json")
CONFIG = os.path.join(RAIZ, "dados", "config.json")
INDEX = os.path.join(RAIZ, "index.html")

TZ_BR = timezone(timedelta(hours=-3))
MARCA_INI = "<!-- OFERTAS:INICIO"
MARCA_FIM = "<!-- OFERTAS:FIM -->"

# Guias existentes, por palavra-chave no titulo do produto.
GUIAS = [
    ("air fryer", "/guias/air-fryer-funcoes/", "Guia: o que cada função da air fryer faz"),
    ("fritadeira", "/guias/air-fryer-funcoes/", "Guia: o que cada função da air fryer faz"),
    ("panificadora", "/guias/panificadora/", "Guia: panificadora vale a pena?"),
    ("frigobar", "/guias/frigobar/", "Guia: como escolher um frigobar"),
    ("cervejeira", "/guias/frigobar/", "Guia: como escolher um frigobar"),
    ("lavadora", "/guias/lavadora/", "Guia: qual lavadora para a sua casa"),
    ("maquina de lavar", "/guias/lavadora/", "Guia: qual lavadora para a sua casa"),
    ("lava e seca", "/guias/lavadora/", "Guia: qual lavadora para a sua casa"),
    ("placa-mae", "/guias/placa-mae-am4/", "Guia: AM4 ainda faz sentido?"),
    ("placa mae", "/guias/placa-mae-am4/", "Guia: AM4 ainda faz sentido?"),
    ("fonte", "/guias/fonte-pc/", "Guia: como escolher a fonte do PC"),
]

# Categoria -> guia padrao (quando o produto nao tem guia especifico)
GUIA_CATEGORIA = {
    "Cozinha": ("/guias/desconto-real/", "Guia: como saber se o desconto é real"),
    "Lavanderia": ("/guias/110v-220v/", "Guia: 110V ou 220V, como não errar"),
    "Casa & Utilidades": ("/guias/110v-220v/", "Guia: 110V ou 220V, como não errar"),
    "Ferramentas & Automotivo": ("/guias/desconto-real/", "Guia: como saber se o desconto é real"),
    "Informática": ("/guias/desconto-real/", "Guia: como saber se o desconto é real"),
    "Casa Inteligente & Áudio": ("/guias/desconto-real/", "Guia: como saber se o desconto é real"),
}

# Ordem de exibicao das secoes
ORDEM = ["Cozinha", "Lavanderia", "Casa & Utilidades", "Informática",
         "Ferramentas & Automotivo", "Casa Inteligente & Áudio"]

ICONE = {
    "Cozinha": "🍳", "Lavanderia": "🧺", "Casa & Utilidades": "🏠",
    "Informática": "💻", "Ferramentas & Automotivo": "🔧", "Casa Inteligente & Áudio": "🔊",
}


def brl(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def encurtar(titulo: str, limite: int = 92) -> str:
    t = " ".join((titulo or "").split())
    if len(t) <= limite:
        return t
    corte = t[:limite]
    for sep in (" - ", ", ", " | ", " "):
        i = corte.rfind(sep)
        if i > limite * 0.55:
            corte = corte[:i]
            break
    return corte.rstrip(" ,-|") + "…"


def guia_para(oferta: dict, categoria: str) -> tuple[str, str]:
    t = (oferta.get("titulo") or oferta.get("titulo_produto") or "").lower()
    for chave, url, rotulo in GUIAS:
        if chave in t:
            return url, rotulo
    if oferta.get("guia"):
        return oferta["guia"], oferta.get("guia_rotulo", "Guia relacionado")
    return GUIA_CATEGORIA.get(categoria, ("/guias/desconto-real/", "Guia: como saber se o desconto é real"))


def data_conferencia(o: dict, padrao: str) -> str:
    """Data/hora da conferencia daquela oferta (fallback: a mais recente do lote)."""
    v = o.get("verificado_em")
    if not v or v == "FALHA_FETCH":
        return padrao
    try:
        dt = datetime.fromisoformat(v).astimezone(TZ_BR)
        return dt.strftime("%d/%m/%Y às %Hh%M")
    except (ValueError, TypeError):
        return padrao


def cartao(o: dict, tag: str, margem_data: str) -> str:
    asin = o["asin"]
    titulo = encurtar(o.get("titulo_produto") or o.get("titulo") or "")
    preco, ref = o.get("preco"), o.get("preco_referencia")
    desc = o.get("desconto_pct")
    cat = o.get("categoria") or "Ofertas"
    est, ava = o.get("estrelas"), o.get("avaliacoes")
    img = o.get("imagem")
    url = f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    guia_url, guia_rot = guia_para(o, cat)

    partes = [f'    <div class="card" data-asin="{asin}">']
    if img:
        partes.append(
            f'      <div class="thumb"><img src="{html.escape(img)}" alt="{html.escape(titulo[:70])}" '
            f'loading="lazy" width="200" height="200"></div>'
        )
    partes.append(f'      <div class="cat-chip">{html.escape(cat)}</div>')
    partes.append(f'      <h3>{html.escape(titulo)}</h3>')

    linha_preco = ['      <div class="price-row">']
    if ref and ref > (preco or 0):
        linha_preco.append(f'<span class="price-was">de {brl(ref)}</span>')
    if preco:
        linha_preco.append(f'<span class="price-now">por {brl(preco)}</span>')
    if desc:
        linha_preco.append(f'<span class="price-off">-{desc}%</span>')
    linha_preco.append("</div>")
    partes.append("".join(linha_preco))

    if est and ava:
        partes.append(f'      <p class="rating">{est} de 5 em {ava:,} avaliações na Amazon</p>'.replace(",", "."))
    if o.get("selo"):
        partes.append(f'      <p class="selo">{html.escape(o["selo"])}</p>')
    if o.get("nota"):
        partes.append(f'      <p class="note">{o["nota"]}</p>')

    partes.append(f'      <p class="verified">Preço conferido em {data_conferencia(o, margem_data)}</p>')
    partes.append(
        f'      <a class="buy" href="{url}" rel="nofollow sponsored" target="_blank" '
        f'rel="noopener">Ver oferta na Amazon</a>'
    )
    partes.append(f'      <a class="ghost" href="{guia_url}">{html.escape(guia_rot)}</a>')
    partes.append("    </div>")
    return "\n".join(partes)


def gerar_bloco(ofertas: list[dict], tag: str) -> str:
    # Só entra na vitrine: disponivel, com preco e com desconto REAL conferido
    # (preco abaixo do preco de referencia informado pela propria Amazon).
    boas = [o for o in ofertas
            if o.get("preco") and o.get("disponivel") and not o.get("descartar")
            and o.get("desconto_pct") and o.get("preco_referencia")
            and o["preco_referencia"] > o["preco"]]

    # data da verificacao (a mais recente)
    datas = [o["verificado_em"] for o in boas if o.get("verificado_em")]
    ref_iso = max(datas) if datas else datetime.now(TZ_BR).isoformat(timespec="seconds")
    dt = datetime.fromisoformat(ref_iso).astimezone(TZ_BR)
    data_txt = dt.strftime("%d/%m/%Y")
    hora_txt = dt.strftime("%Hh%M")
    margem_data = f"{data_txt} às {hora_txt}"

    por_cat: dict[str, list[dict]] = {}
    for o in boas:
        por_cat.setdefault(o.get("categoria") or "Ofertas", []).append(o)

    cats = [c for c in ORDEM if c in por_cat] + [c for c in por_cat if c not in ORDEM]

    linhas = [
        f"{MARCA_INI} — gerado por tools/gerar_site.py em {dt.strftime('%d/%m/%Y %H:%M')}. "
        f"NÃO editar à mão: rode o gerador.] -->",
        f'  <div class="aviso-precos">',
        f'    <p><b>{len(boas)} ofertas com desconto real</b>, conferidas uma por uma na Amazon em '
        f'<b>{margem_data}</b> — preço abaixo do preço de referência, item disponível e anúncio do '
        f'mesmo produto conferido. Preços e estoque mudam a qualquer momento: confira o valor final '
        f'na página do produto. Veja <a href="/como-verificamos/">como verificamos</a> e o que '
        f'acontece com <a href="/como-verificamos/#vencida">oferta vencida</a>.</p>',
        f'  </div>',
        "",
    ]

    for cat in cats:
        lst = sorted(por_cat[cat], key=lambda x: -(x.get("desconto_pct") or 0))
        linhas.append('  <div class="section-title">')
        linhas.append(f'    <h2>{ICONE.get(cat, "🛒")} {html.escape(cat)}</h2><div class="bar"></div>')
        linhas.append(f'    <span class="updated">{len(lst)} ofertas conferidas</span>')
        linhas.append('  </div>')
        linhas.append('  <div class="grid">')
        for o in lst:
            linhas.append(cartao(o, tag, margem_data))
        linhas.append('  </div>')
        linhas.append("")

    linhas.append("  " + MARCA_FIM)
    return "\n".join(linhas)


def main() -> None:
    dry = "--dry-run" in sys.argv
    dados = json.load(open(DADOS, encoding="utf-8"))
    cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {}
    tag = cfg.get("tag_afiliado", "dutr4oferta00-20")
    ofertas = dados["ofertas"]

    bloco = gerar_bloco(ofertas, tag)
    html_atual = open(INDEX, encoding="utf-8").read()

    ini = html_atual.find(MARCA_INI)
    fim = html_atual.find(MARCA_FIM)
    if ini == -1 or fim == -1:
        print("ERRO: marcadores OFERTAS:INICIO/FIM nao encontrados no index.html")
        sys.exit(1)
    fim += len(MARCA_FIM)

    novo = html_atual[:ini] + bloco + html_atual[fim:]
    validas = len([o for o in ofertas if o.get("preco") and o.get("disponivel") and not o.get("descartar")])
    print(f"ofertas validas no bloco: {validas}")
    print(f"tamanho do bloco: {len(bloco)} chars (antes: {fim - ini})")

    if dry:
        print("\n--- previa (primeiros 1200 chars) ---")
        print(bloco[:1200])
        return

    open(INDEX, "w", encoding="utf-8", newline="\n").write(novo)
    print(f"index.html atualizado ({len(novo)} bytes)")


if __name__ == "__main__":
    main()
