#!/usr/bin/env python3
"""Atualizacao leve das ofertas JA publicadas.

Le dados/ofertas.json (as ofertas que estao no ar), reconfere preco e
disponibilidade de cada uma na pagina do produto e:
  - atualiza o preco exibido quando mudou;
  - remove a oferta quando ficou indisponivel ou perdeu o desconto real;
  - guarda a data/hora da nova conferencia.

E o que mantem a vitrine sem oferta vencida entre as rodadas completas.
Uso: python3 tools/refrescar_publicados.py [--limite N]
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "dados", "ofertas.json")
ESTADO = os.path.join(os.environ.get("VITRINE_WORK", "/tmp"), "selecao_verificada.json")
PAUSA = float(os.environ.get("VITRINE_PAUSA", "3"))
TZ = timezone(timedelta(hours=-3))

spec = importlib.util.spec_from_file_location("col", os.path.join(RAIZ, "tools", "coletar_ofertas.py"))
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)

LIMITE = 999
if "--limite" in sys.argv:
    LIMITE = int(sys.argv[sys.argv.index("--limite") + 1])


def main() -> None:
    dados = json.load(open(DADOS, encoding="utf-8"))
    ofertas = dados["ofertas"]

    publicadas = [o for o in ofertas if o.get("desconto_pct") and o.get("disponivel") and o.get("preco")]
    print(f"ofertas publicadas a reconferir: {len(publicadas)} (limite {LIMITE})", flush=True)

    agora = datetime.now(TZ).isoformat(timespec="seconds")
    atualizadas, removidas, sem_leitura = [], [], []
    por_asin = {o["asin"]: o for o in publicadas}

    for i, o in enumerate(publicadas[:LIMITE], 1):
        info = col.info_produto(o["asin"])
        if not info or not info.get("preco"):
            # falha de leitura nao prova invalidez: mantem e tenta na proxima
            sem_leitura.append(o["asin"])
            print(f"  [{i}] {o['asin']}: sem leitura (mantida)", flush=True)
            time.sleep(PAUSA * 2)
            continue

        if not info["disponivel"]:
            removidas.append((o["asin"], f"indisponivel ({info['indisponivel_motivo']})"))
            print(f"  [{i}] {o['asin']}: REMOVIDA (indisponivel)", flush=True)
            continue

        preco_antigo = o["preco"]
        o["preco"] = info["preco"]
        if info.get("preco_referencia"):
            o["preco_referencia"] = max(info["preco_referencia"], o.get("preco_referencia") or 0)
        if o.get("preco_referencia") and o["preco_referencia"] > o["preco"]:
            o["desconto_pct"] = round((1 - o["preco"] / o["preco_referencia"]) * 100)
        else:
            removidas.append((o["asin"], "sem desconto real agora"))
            print(f"  [{i}] {o['asin']}: REMOVIDA (desconto acabou)", flush=True)
            continue
        o["verificado_em"] = agora
        if info.get("estrelas"):
            o["estrelas"] = info["estrelas"]
        if abs(o["preco"] - preco_antigo) > 0.01:
            atualizadas.append((o["asin"], preco_antigo, o["preco"]))
            print(f"  [{i}] {o['asin']}: preco R${preco_antigo:.2f} -> R${o['preco']:.2f} (-{o['desconto_pct']}%)", flush=True)
        else:
            print(f"  [{i}] {o['asin']}: OK R${o['preco']:.2f}", flush=True)
        time.sleep(PAUSA)

    # tira do arquivo o que saiu
    ids_removidos = {a for a, _ in removidas}
    dados["ofertas"] = [o for o in ofertas if o["asin"] not in ids_removidos]
    dados["gerado_em"] = datetime.now(TZ).isoformat(timespec="seconds")
    dados["total"] = len(dados["ofertas"])
    json.dump(dados, open(DADOS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # mantem o estado do pipeline coerente com o que foi publicado
    if os.path.exists(ESTADO):
        est = json.load(open(ESTADO, encoding="utf-8"))
        por_id = {o["asin"]: o for o in dados["ofertas"]}
        novos = []
        for o in est["ofertas"]:
            if o["asin"] in por_id:
                novos.append(por_id[o["asin"]])
            elif o["asin"] in ids_removidos:
                continue  # saiu da vitrine
            else:
                novos.append(o)
        for a, o in por_id.items():
            if a not in {x["asin"] for x in novos}:
                novos.append(o)
        est["ofertas"] = novos
        est["total"] = len(novos)
        json.dump(est, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"estado sincronizado: {len(novos)} itens", flush=True)

    print("\n===== RESUMO DO REFRESH =====")
    print(f"publicadas no ar agora: {len(dados['ofertas'])}")
    print(f"precos atualizados: {len(atualizadas)} -> {atualizadas[:8]}")
    print(f"removidas: {len(removidas)} -> {removidas}")
    print(f"sem leitura (mantidas, tentar de novo): {len(sem_leitura)} -> {sem_leitura[:6]}")


if __name__ == "__main__":
    main()
