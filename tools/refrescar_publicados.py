#!/usr/bin/env python3
"""Atualizacao leve das ofertas JA publicadas (reconferencia de preco/estoque).

Le dados/ofertas.json, reconfere cada oferta publicada na pagina do produto e:
  - atualiza o preco exibido quando mudou (exige leitura confiavel e, se a
    mudanca passar de 20%, uma SEGUNDA leitura que confirme);
  - remove a oferta quando o anuncio esta explicitamente indisponivel ou perdeu
    o desconto real;
  - guarda a data/hora da nova conferencia.

Guardas de integridade (aprendidos na pratica):
  - o titulo lido tem de casar com o titulo publicado (evita pegar outro produto);
  - pagina sem preco e sem aviso de indisponibilidade = leitura degradada, nao e
    prova de nada: a oferta e mantida como esta;
  - se mais de 25% das leituras falharem, a rodada ABORTA sem publicar nada
    (sinal de bloqueio/instabilidade de rede, nao de ofertas invalidas).

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

MAX_MUDANCA = 0.20      # acima disso, exige segunda leitura independente
MAX_FALHAS = 0.25       # acima disso, aborta a rodada sem publicar


def carrega(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


col = carrega("col", os.path.join(RAIZ, "tools", "coletar_ofertas.py"))
ver = carrega("ver", os.path.join(RAIZ, "tools", "verificar_ofertas.py"))

LIMITE = 999
if "--limite" in sys.argv:
    LIMITE = int(sys.argv[sys.argv.index("--limite") + 1])


def leitura_confiavel(o: dict, info: dict | None) -> tuple[bool, str]:
    """A leitura serve para decidir algo? Titulo tem de casar e a pagina precisa
    ter preco ou aviso explicito de indisponibilidade."""
    if not info:
        return False, "sem leitura (fetch falhou/bloqueado)"
    if not info.get("titulo"):
        return False, "pagina sem titulo"
    ok, jac = ver.titulo_casa(o.get("titulo") or o.get("titulo_produto") or "", info["titulo"])
    if not ok:
        return False, f"titulo nao casa (j={jac})"
    if info.get("preco") is None and info.get("indisponivel_motivo") != "fora de estoque":
        return False, "pagina sem preco (leitura degradada)"
    return True, ""


def main() -> None:
    dados = json.load(open(DADOS, encoding="utf-8"))
    ofertas = dados["ofertas"]
    publicadas = [o for o in ofertas
                  if o.get("desconto_pct") and o.get("disponivel") and o.get("preco")][:LIMITE]
    print(f"ofertas publicadas a reconferir: {len(publicadas)}", flush=True)

    agora = datetime.now(TZ).isoformat(timespec="seconds")
    atualizadas, removidas, sem_leitura, suspeitas = [], [], [], []

    # leitura em lote com navegador real (confiavel); curl entra só como reserva
    lote = col.info_produtos_lote([o["asin"] for o in publicadas])
    if lote:
        print(f"leitura com navegador: {len(lote)}/{len(publicadas)} paginas", flush=True)

    for i, o in enumerate(publicadas, 1):
        asin = o["asin"]
        info = lote.get(asin) or col.info_produto(asin)
        ok, motivo = leitura_confiavel(o, info)
        if not ok:
            sem_leitura.append((asin, motivo))
            print(f"  [{i}] {asin}: MANTIDA ({motivo})", flush=True)
            time.sleep(PAUSA * 2)
            continue

        # indisponivel de verdade (titulo casou e o anuncio avisa indisponibilidade)
        if not info["disponivel"] and info.get("indisponivel_motivo") == "fora de estoque":
            removidas.append((asin, "anuncio indisponivel (confirmado no titulo)"))
            print(f"  [{i}] {asin}: REMOVIDA (indisponivel)", flush=True)
            continue

        novo_preco = info["preco"]
        antigo = o["preco"]
        # mudanca grande exige confirmacao independente
        if antigo and abs(novo_preco - antigo) / antigo > MAX_MUDANCA:
            time.sleep(PAUSA)
            conf = col.info_produto(asin)
            okc, _ = leitura_confiavel(o, conf)
            if not okc or conf.get("preco") is None or abs(conf["preco"] - novo_preco) / novo_preco > 0.01:
                suspeitas.append((asin, antigo, novo_preco))
                print(f"  [{i}] {asin}: MUDANCA NAO CONFIRMADA "
                      f"(R${antigo:.2f} -> R${novo_preco:.2f}); mantido o antigo", flush=True)
                continue

        o["preco"] = novo_preco
        if info.get("preco_referencia"):
            o["preco_referencia"] = max(info["preco_referencia"], o.get("preco_referencia") or 0)
        if o.get("preco_referencia") and o["preco_referencia"] > o["preco"]:
            o["desconto_pct"] = round((1 - o["preco"] / o["preco_referencia"]) * 100)
        else:
            removidas.append((asin, "desconto real acabou"))
            print(f"  [{i}] {asin}: REMOVIDA (sem desconto real)", flush=True)
            continue
        o["verificado_em"] = agora
        if info.get("estrelas"):
            o["estrelas"] = info["estrelas"]
        if abs(o["preco"] - antigo) > 0.01:
            atualizadas.append((asin, antigo, o["preco"]))
            print(f"  [{i}] {asin}: R${antigo:.2f} -> R${o['preco']:.2f} (-{o['desconto_pct']}%)", flush=True)
        else:
            print(f"  [{i}] {asin}: OK R${o['preco']:.2f}", flush=True)
        time.sleep(PAUSA)

    # ---- guarda de integridade: muitas falhas = bloqueio/rede, nao oferta ruim ----
    if publicadas and len(sem_leitura) / len(publicadas) > MAX_FALHAS:
        print(f"\nABORTADO: {len(sem_leitura)}/{len(publicadas)} leituras falharam "
              f"(> {int(MAX_FALHAS*100)}%) — nada foi alterado nem publicado", flush=True)
        print("causa provavel: bloqueio temporario do IP pela Amazon ou rede instavel", flush=True)
        sys.exit(2)

    ids_removidos = {a for a, _ in removidas}
    dados["ofertas"] = [o for o in ofertas if o["asin"] not in ids_removidos]
    dados["gerado_em"] = agora
    dados["total"] = len(dados["ofertas"])
    json.dump(dados, open(DADOS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if os.path.exists(ESTADO):
        est = json.load(open(ESTADO, encoding="utf-8"))
        por_id = {o["asin"]: o for o in dados["ofertas"]}
        novos, vistos = [], set()
        for o in est["ofertas"]:
            a = o["asin"]
            if a in ids_removidos or a in vistos:
                continue
            vistos.add(a)
            novos.append(por_id.get(a, o))
        for a, o in por_id.items():
            if a not in vistos:
                novos.append(o)
                vistos.add(a)
        est["ofertas"], est["total"] = novos, len(novos)
        json.dump(est, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"estado sincronizado: {len(novos)} itens", flush=True)

    print("\n===== RESUMO DO REFRESH =====")
    print(f"ofertas no ar agora: {len(dados['ofertas'])}")
    print(f"precos atualizados: {len(atualizadas)} -> {atualizadas[:8]}")
    print(f"removidas: {len(removidas)} -> {removidas}")
    print(f"mudancas nao confirmadas (mantidas): {len(suspeitas)} -> {suspeitas[:6]}")
    print(f"sem leitura (mantidas): {len(sem_leitura)}/{len(publicadas)}")


if __name__ == "__main__":
    main()
