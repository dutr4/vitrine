#!/usr/bin/env python3
"""Verifica (ou reverifica) apenas os itens de dados/destaques.json que estao sem
preco disponivel valido. Ritmo lento para nao disparar o anti-bot da Amazon.

Uso: python3 tools/verificar_destaques.py [pausa_segundos]
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTAQUES = os.path.join(RAIZ, "dados", "destaques.json")
spec = importlib.util.spec_from_file_location("col", os.path.join(RAIZ, "tools", "coletar_ofertas.py"))
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)
TZ = timezone(timedelta(hours=-3))
PAUSA_PADRAO = float(os.environ.get("VITRINE_PAUSA", "6"))


def main() -> None:
    pausa = float(sys.argv[1]) if len(sys.argv) > 1 else PAUSA_PADRAO
    d = json.load(open(DESTAQUES, encoding="utf-8"))
    itens = d["itens"]
    pendentes = [i for i in itens if not (i.get("preco") and i.get("disponivel"))]
    print(f"itens={len(itens)} pendentes={len(pendentes)} pausa={pausa}s", flush=True)

    for i, it in enumerate(pendentes, 1):
        info = col.info_produto(it["asin"])
        if not info or not info.get("preco"):
            print(f"  [{i}/{len(pendentes)}] {it['asin']}: FALHA", flush=True)
            time.sleep(pausa * 2)
            continue
        it["preco"] = info["preco"]
        it["disponivel"] = info["disponivel"]
        it["titulo_produto"] = info["titulo"]
        it["estrelas"] = info.get("estrelas")
        it["avaliacoes"] = info.get("avaliacoes")
        it["imagem"] = info.get("imagem") or it.get("imagem")
        it["preco_referencia"] = info.get("preco_referencia") if (
            info.get("preco_referencia") and info["preco_referencia"] > info["preco"]) else None
        it["desconto_pct"] = (round((1 - it["preco"] / it["preco_referencia"]) * 100)
                              if it["preco_referencia"] else None)
        it["verificado_em"] = datetime.now(TZ).isoformat(timespec="seconds")
        it["descartar"] = None if info["disponivel"] else "indisponivel"
        d["itens"] = itens
        json.dump(d, open(DESTAQUES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  [{i}/{len(pendentes)}] {it['asin']}: R${it['preco']} "
              f"{'de R$%.2f' % it['preco_referencia'] if it['preco_referencia'] else 'sem ref'} "
              f"disp={info['disponivel']} | {info['titulo'][:38]}", flush=True)
        time.sleep(pausa)

    ok = [i for i in itens if i.get("preco") and i.get("disponivel") and not i.get("descartar")]
    print(f"\nfim: {len(ok)}/{len(itens)} destaques validos", flush=True)


if __name__ == "__main__":
    main()
