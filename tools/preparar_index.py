#!/usr/bin/env python3
"""Prepara o index.html para o gerador: insere marcadores OFERTAS:INICIO/FIM
no lugar da secao antiga de ofertas e adiciona o CSS de precos/verificacao.

Idempotente: se os marcadores ja existirem, nao mexe na estrutura.
Uso: python3 tools/preparar_index.py
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(RAIZ, "index.html")

CSS_NOVO = """  .card{ position:relative; }
  .thumb{
    background:linear-gradient(140deg, var(--surface-2), #0e1a3d); border:1px solid var(--line);
    border-radius:10px; height:150px; display:flex; align-items:center; justify-content:center; padding:10px;
  }
  .thumb img{ max-height:130px; max-width:100%; object-fit:contain; }
  .cat-chip{ color:var(--muted); font-size:10px; letter-spacing:.12em; text-transform:uppercase; font-weight:700; }
  .card h3{ display:-webkit-box; -webkit-line-clamp:3; line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
  .price-row{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
  .price-was{ color:var(--muted); font-size:12.5px; text-decoration:line-through; }
  .price-now{ color:var(--gold-light); font-size:19px; font-weight:700; }
  .price-off{ background:rgba(56,149,224,.16); color:var(--blue); font-size:12px; font-weight:700; padding:2px 8px; border-radius:999px; }
  .rating{ color:var(--muted); font-size:12px; margin:0; }
  .selo{ color:var(--blue); font-size:12px; margin:0; font-weight:600; }
  .verified{ color:#6b7a99; font-size:11px; margin:0; }
  .aviso-precos{
    margin:26px 0 0; padding:16px 20px; border:1px solid var(--line);
    border-left:3px solid var(--gold); border-radius:12px; background:var(--surface);
  }
  .aviso-precos p{ margin:0; color:var(--muted); font-size:13.5px; }
  .aviso-precos a{ color:var(--blue); }
</style>"""


def main() -> None:
    html = open(INDEX, encoding="utf-8").read()

    # 1) marcadores no lugar da secao antiga de ofertas
    if "<!-- OFERTAS:INICIO" not in html:
        ini = html.find('  <div class="section-title">\n    <h2>Cozinha</h2>')
        fim = html.find('  <div class="section-title">\n    <h2>Análises de produtos</h2>')
        if ini == -1 or fim == -1:
            print("ERRO: nao achei os limites da secao de ofertas")
            sys.exit(1)
        removido = html[ini:fim]
        html = (html[:ini]
                + "  <!-- OFERTAS:INICIO -->\n\n  <!-- OFERTAS:FIM -->\n\n"
                + html[fim:])
        print(f"marcadores inseridos (removidos {len(removido)} chars de ofertas antigas)")
    else:
        print("marcadores ja existem")

    # 2) CSS de precos
    if ".price-now" not in html:
        if "</style>" not in html:
            print("ERRO: nao achei o bloco <style>")
            sys.exit(1)
        html = html.replace("</style>", CSS_NOVO, 1)
        print("CSS de precos/verificacao adicionado")
    else:
        print("CSS de precos ja existe")

    open(INDEX, "w", encoding="utf-8", newline="\n").write(html)
    print(f"index.html salvo ({len(html)} bytes)")


if __name__ == "__main__":
    main()
