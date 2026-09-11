#!/usr/bin/env python3
"""Extrai os cards de curadoria original do index.html para dados/destaques.json.

Preserva a nota editorial, a categoria, o ASIN e o link de guia/analise de cada
produto que ja estava no site, para que o gerador nao perca esse conteudo.
Depois verifica preco/disponibilidade de cada um.
"""
import html as htmllib
import importlib.util
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(RAIZ, "index.html")
SAIDA = os.path.join(RAIZ, "dados", "destaques.json")

spec = importlib.util.spec_from_file_location("col", os.path.join(RAIZ, "tools", "coletar_ofertas.py"))
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)
TZ = timezone(timedelta(hours=-3))


def main() -> None:
    html = open(INDEX, encoding="utf-8").read()
    # recorta o trecho de ofertas (antes dos cards de analise/guia)
    i = html.find("<!-- OFERTAS:INICIO")
    if i == -1:
        i = 0
    j = html.find('<h2>Análises de produtos</h2>')
    trecho = html[i:j if j > 0 else len(html)]

    # Cada card termina com "\n    </div>" (o conteudo interno usa 6 espacos).
    pedacos = trecho.split('<div class="card">')[1:]
    cards = []
    for p in pedacos:
        corte = p.find("\n    </div>")
        cards.append(p[:corte] if corte > 0 else p)
    print(f"blocos de card encontrados: {len(cards)}")

    itens = []
    for c in cards:
        m_asin = re.search(r'/dp/([A-Z0-9]{10})', c)
        if not m_asin:
            continue
        cat = re.search(r'<div class="cat">([^<]+)</div>', c)
        tit = re.search(r"<h3>(.*?)</h3>", c, re.S)
        nota = re.search(r'<p class="note">(.*?)</p>', c, re.S)
        ghost = re.search(r'<a class="ghost" href="([^"]+)">([^<]+)</a>', c)
        itens.append({
            "asin": m_asin.group(1),
            "categoria_original": htmllib.unescape(cat.group(1).strip()) if cat else None,
            "titulo_site": htmllib.unescape(re.sub("<[^>]+>", "", tit.group(1)).strip()) if tit else None,
            "nota": re.sub(r"\s+", " ", nota.group(1)).strip() if nota else None,
            "guia": ghost.group(1) if ghost else None,
            "guia_rotulo": htmllib.unescape(ghost.group(2)).strip() if ghost else None,
        })

    print(f"cards de curadoria extraidos: {len(itens)}")
    for it in itens:
        print(f"  {it['asin']} | {it['categoria_original']} | {it['titulo_site'][:50] if it['titulo_site'] else '?'}")

    # verifica preco/disponibilidade de cada um
    print("\nverificando precos...")
    for it in itens:
        info = col.info_produto(it["asin"])
        if not info:
            it["descartar"] = "falha ao ler a pagina"
            print(f"  {it['asin']}: FALHA")
            continue
        it["preco"] = info["preco"]
        it["preco_referencia"] = info.get("preco_referencia")
        it["disponivel"] = info["disponivel"]
        it["titulo_produto"] = info["titulo"]
        it["estrelas"] = info.get("estrelas")
        it["avaliacoes"] = info.get("avaliacoes")
        it["imagem"] = info.get("imagem")
        it["verificado_em"] = datetime.now(TZ).isoformat(timespec="seconds")
        if it["preco"] and it["preco_referencia"] and it["preco_referencia"] > it["preco"]:
            it["desconto_pct"] = round((1 - it["preco"] / it["preco_referencia"]) * 100)
        else:
            it["preco_referencia"] = None
        if not info["disponivel"]:
            it["descartar"] = "indisponivel"
        print(f"  {it['asin']}: R${it['preco']} "
              f"{'de R$%.2f' % it['preco_referencia'] if it['preco_referencia'] else 'sem ref'} "
              f"disp={info['disponivel']}")
        time.sleep(1.5)

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    json.dump({"itens": itens}, open(SAIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nsalvo: {SAIDA}")


if __name__ == "__main__":
    main()
