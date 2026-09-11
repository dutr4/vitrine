#!/usr/bin/env python3
"""Amplia a selecao: pega candidatos ainda nao verificados do pool bruto e
adiciona a /tmp/selecao_verificada.json (o verificador processa depois).

Uso: python3 expandir_selecao.py [por_categoria]
"""
import importlib.util
import json
import sys
from collections import defaultdict

BASE = "/mnt/c/Users/dutr4/Documents/vitrine-local/vitrine.dutr4.com.br/tools"


def carregar_mod(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


curar = carregar_mod("curar", f"{BASE}/curar_ofertas.py")

POR_CAT = int(sys.argv[1]) if len(sys.argv) > 1 else 15
VERIFICADA = "/tmp/selecao_verificada.json"
BRUTO = "/tmp/ofertas_busca.json"

ver = json.load(open(VERIFICADA, encoding="utf-8"))
atuais = {o["asin"] for o in ver["ofertas"]}
print(f"ja na selecao: {len(atuais)}")

bruto = json.load(open(BRUTO, encoding="utf-8"))["ofertas"]
vistos, unicas = set(), []
for o in bruto:
    if o["asin"] in vistos or o["asin"] in atuais:
        continue
    vistos.add(o["asin"])
    unicas.append(o)

cands = []
for o in unicas:
    if o.get("patrocinado") or not o.get("preco") or not o.get("preco_referencia") or not o.get("titulo"):
        continue
    desc = (1 - o["preco"] / o["preco_referencia"]) * 100
    if desc < 12:
        continue
    cat = curar.categorizar(o["titulo"])
    if not cat:
        continue
    if (o.get("avaliacoes") or 0) < 30 or (o.get("estrelas") or 0) < 4.0:
        continue
    o["desconto_pct"] = round(desc)
    o["categoria"] = cat
    cands.append(o)

por_cat = defaultdict(list)
for o in cands:
    por_cat[o["categoria"]].append(o)

novos = []
for cat, lst in por_cat.items():
    lst.sort(key=lambda x: -(x["desconto_pct"] * min(x["avaliacoes"], 5000) ** 0.35))
    escolhidos = lst[:POR_CAT]
    novos.extend(escolhidos)
    print(f"  {cat}: {len(lst)} candidatos -> {len(escolhidos)} escolhidos")
    for o in escolhidos:
        print(f"      {o['desconto_pct']:2}% R${o['preco']:>8.2f} (de R${o['preco_referencia']:.2f}) "
              f"{o['estrelas']}*({o['avaliacoes']}) {o['titulo'][:46]}")

ver["ofertas"].extend(novos)
ver["total"] = len(ver["ofertas"])
json.dump(ver, open(VERIFICADA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\nadicionados {len(novos)} candidatos -> total {ver['total']} (a verificar)")
