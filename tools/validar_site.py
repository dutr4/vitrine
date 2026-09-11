#!/usr/bin/env python3
"""Valida o index.html gerado: cards, precos, links de afiliado, links internos.

Uso: python3 tools/validar_site.py
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(RAIZ, "index.html")

falhas = []


def main() -> None:
    html = open(INDEX, encoding="utf-8").read()
    print(f"index.html: {len(html)} bytes")

    # 1) cards e precos
    cards = re.findall(r'<div class="card" data-asin="([A-Z0-9]{10})">(.*?)\n    </div>', html, re.S)
    print(f"cards com ASIN: {len(cards)}")
    sem_preco = [a for a, c in cards if 'class="price-now"' not in c]
    sem_off = [a for a, c in cards if 'class="price-off"' not in c]
    sem_data = [a for a, c in cards if 'class="verified"' not in c]
    sem_img = [a for a, c in cards if "<img" not in c]
    if sem_preco:
        falhas.append(f"cards sem preco: {sem_preco}")
    if sem_off:
        falhas.append(f"cards sem % de desconto: {sem_off}")
    if sem_data:
        falhas.append(f"cards sem data de conferencia: {sem_data}")
    if sem_img:
        falhas.append(f"cards sem imagem: {sem_img}")

    # 2) ASINs duplicados
    asins = [a for a, _ in cards]
    dups = {a for a in asins if asins.count(a) > 1}
    if dups:
        falhas.append(f"ASINs duplicados: {dups}")
    print(f"ASINs unicos: {len(set(asins))}")

    # 3) links de afiliado: tag + rel
    buy = re.findall(r'<a class="buy" href="([^"]+)"([^>]*)>', html)
    sem_tag = [u for u, _ in buy if "amazon.com.br" in u and "tag=" not in u]
    sem_rel = [(u, at) for u, at in buy if "amazon.com.br" in u and "nofollow" not in at]
    if sem_tag:
        falhas.append(f"links Amazon sem tag: {sem_tag}")
    if sem_rel:
        falhas.append(f"links Amazon sem rel=nofollow: {sem_rel[:3]}")
    tags = set(re.findall(r'tag=([a-z0-9\-]+)', html))
    print(f"links 'buy': {len(buy)} | tags usadas: {tags}")

    # 4) imagens da Amazon
    imgs = re.findall(r'<img src="(https://m\.media-amazon\.com[^"]+)"', html)
    print(f"imagens de produto: {len(imgs)}")
    ruins = [i for i in imgs if not re.search(r"\.(jpg|png|webp)$", i)]
    if ruins:
        falhas.append(f"URLs de imagem suspeitas: {ruins[:3]}")

    # 5) links internos: existem no disco?
    internos = sorted(set(re.findall(r'href="(/[^"#?]*)"', html)))
    quebrados = []
    for l in internos:
        alvo = os.path.join(RAIZ, l.strip("/").replace("/", os.sep))
        if l.endswith("/"):
            alvo = os.path.join(alvo, "index.html")
        if not os.path.exists(alvo):
            quebrados.append(l)
    print(f"links internos unicos: {len(internos)}")
    if quebrados:
        falhas.append(f"links internos quebrados: {quebrados}")

    # 6) disclosure presente
    if "Associado da Amazon" not in html:
        falhas.append("sem divulgacao de associado na home")

    print()
    if falhas:
        print("FALHAS:")
        for f in falhas:
            print("  -", f)
        sys.exit(1)
    print("TUDO OK")


if __name__ == "__main__":
    main()
