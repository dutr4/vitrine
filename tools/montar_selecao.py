#!/usr/bin/env python3
"""Monta a selecao final: reaplica TODOS os filtros no pool bruto, preserva o que
ja foi verificado e mantem uma lista negra dos ASINs descartados.

Gera /tmp/selecao_final.json no mesmo formato usado pelo verificador.

Uso: python3 montar_selecao.py [por_categoria]
"""
import importlib.util
import json
import os
import sys
from collections import defaultdict

# Diretorio de trabalho (arquivos intermediarios). Sobrescreva com VITRINE_WORK.
WORK = os.environ.get("VITRINE_WORK", "/tmp")

BASE = "/mnt/c/Users/dutr4/Documents/vitrine-local/vitrine.dutr4.com.br/tools"


def carregar_mod(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


curar = carregar_mod("curar", f"{BASE}/curar_ofertas.py")

POR_CAT = int(sys.argv[1]) if len(sys.argv) > 1 else 18
BRUTO = f"{WORK}/ofertas_busca.json"
VERIF = f"{WORK}/selecao_verificada.json"
SAIDA = f"{WORK}/selecao_final.json"

verif = json.load(open(VERIF, encoding="utf-8"))["ofertas"]
por_asin = {o["asin"]: o for o in verif}
print(f"registro anterior: {len(verif)} itens")

# 1) o que ja foi verificado e continua valido pelos filtros novos
validos, descartados = [], set()
for o in verif:
    if o.get("descartar"):
        descartados.add(o["asin"])
        continue
    if o.get("verificado_em") == "FALHA_FETCH":
        descartados.add(o["asin"])
        continue
    if o.get("verificado_em") and o.get("disponivel") and o.get("preco"):
        if curar.bloqueado(o.get("titulo_produto") or o.get("titulo", "")):
            descartados.add(o["asin"])
            continue
        validos.append(o)
print(f"  validos ja verificados: {len(validos)} | descartados (lista negra): {len(descartados)}")

# 2) candidatos novos do pool bruto
bruto = json.load(open(BRUTO, encoding="utf-8"))["ofertas"]
usados = {o["asin"] for o in validos} | descartados | {o["asin"] for o in verif if o.get("verificado_em")}
vistos, cands = set(), []
for o in bruto:
    a = o["asin"]
    if a in vistos or a in usados or a in descartados:
        continue
    vistos.add(a)
    if o.get("patrocinado") or not o.get("preco") or not o.get("preco_referencia") or not o.get("titulo"):
        continue
    if o["preco"] < curar.PRECO_MINIMO or curar.bloqueado(o["titulo"]):
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
print(f"  candidatos novos (filtrados): {len(cands)}")

# 3) completa cada categoria ate POR_CAT
por_cat = defaultdict(list)
for o in validos:
    por_cat[o.get("categoria") or curar.categorizar(o.get("titulo_produto") or o.get("titulo", ""))].append(o)
for o in cands:
    por_cat[o["categoria"]].append(o)

final = []
for cat, lst in sorted(por_cat.items()):
    # ja verificados primeiro (sao garantidos); depois os novos por qualidade
    ja = [x for x in lst if x.get("verificado_em") and not x.get("descartar")]
    novos = [x for x in lst if not x.get("verificado_em")]
    novos.sort(key=lambda x: -((x.get("desconto_pct") or 0) * min(x.get("avaliacoes") or 0, 5000) ** 0.35))
    escolhidos = ja + novos[: max(0, POR_CAT - len(ja))]
    final.extend(escolhidos)
    print(f"  {cat}: {len(ja)} verificados + {len(escolhidos) - len(ja)} novos = {len(escolhidos)}")

json.dump({"total": len(final), "ofertas": final}, open(SAIDA, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
pend = [o for o in final if not o.get("verificado_em")]
print(f"\nselecao final: {len(final)} ofertas | a verificar: {len(pend)}")
print(f"salvo em {SAIDA}")
