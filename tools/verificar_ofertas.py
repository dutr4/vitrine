#!/usr/bin/env python3
"""Verifica cada oferta na pagina do produto: preco, disponibilidade, titulo e referencia.

Regra de ouro: a PAGINA DO PRODUTO e a fonte da verdade. Preco e disponibilidade
vem dela. O "De:" (preco de referencia) so e aceito quando:
  a) a propria pagina do produto mostra o preco riscado, ou
  b) o titulo do card de busca casa com o titulo do produto (mesma variante)
     e o preco riscado da busca e maior que o preco verificado.

Uso: python3 verificar_ofertas.py [lote] [--refazer]
"""
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone

# Diretorio de trabalho (arquivos intermediarios). Sobrescreva com VITRINE_WORK.
WORK = os.environ.get("VITRINE_WORK", "/tmp")
# Pausa entre requisicoes a Amazon (segundos). No cron use 3 para ser conservador.
PAUSA = float(os.environ.get("VITRINE_PAUSA", "1.5"))

BASE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("col", f"{BASE}/coletar_ofertas.py")
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)

TZ = timezone(timedelta(hours=-3))
ENTRADA = f"{WORK}/selecao.json"
SAIDA = f"{WORK}/selecao_verificada.json"


def tokens(txt: str) -> set[str]:
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return {p for p in t.split() if len(p) >= 4}


def titulo_casa(a: str, b: str) -> tuple[bool, float]:
    """Compara titulos: Jaccard + presenca dos tokens do modelo (numeros/letras)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False, 0.0
    jac = len(ta & tb) / len(ta | tb)
    # tokens de modelo: com digitos (ex.: 1000, na120, 4.2l, b550m)
    mod_a = {p for p in ta if any(c.isdigit() for c in p)}
    mod_b = {p for p in tb if any(c.isdigit() for c in p)}
    mod_ok = (len(mod_a & mod_b) / len(mod_a)) if mod_a else True
    return (jac >= 0.30 and mod_ok >= 0.5), round(jac, 2)


def carregar(refazer: bool) -> list[dict]:
    if os.path.exists(SAIDA) and not refazer:
        return json.load(open(SAIDA, encoding="utf-8"))["ofertas"]
    return json.load(open(ENTRADA, encoding="utf-8"))["ofertas"]


def salvar(lst: list[dict]) -> None:
    json.dump({"total": len(lst), "ofertas": lst}, open(SAIDA, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refazer = "--refazer" in sys.argv
    limite = int(args[0]) if args else 30

    ofertas = carregar(refazer)
    if refazer:
        for o in ofertas:
            o.pop("verificado_em", None)

    feitos = 0
    for o in ofertas:
        if o.get("verificado_em") or feitos >= limite:
            if feitos >= limite:
                break
            continue
        info = col.info_produto(o["asin"])
        feitos += 1
        agora = datetime.now(TZ).isoformat(timespec="seconds")
        if not info or not info.get("preco"):
            # nao marca como verificado: a proxima execucao tenta de novo
            o["tentativas_falhas"] = (o.get("tentativas_falhas") or 0) + 1
            if o["tentativas_falhas"] >= 3:
                o["verificado_em"] = "FALHA_FETCH"
                o["descartar"] = "falha ao ler a pagina do produto (3 tentativas)"
            salvar(ofertas)
            print(f"  [{feitos}] {o['asin']}: FALHA (tentativa {o['tentativas_falhas']})", file=sys.stderr)
            time.sleep(4)
            continue

        casa, jac = titulo_casa(o.get("titulo", ""), info["titulo"])
        preco_busca, ref_busca = o.get("preco"), o.get("preco_referencia")

        o["preco"] = info["preco"]
        o["titulo_produto"] = info["titulo"]
        o["disponivel"] = info["disponivel"]
        o["titulo_confere"] = casa
        o["titulo_jaccard"] = jac
        # estrelas/avaliacoes: o card da busca (listagem) e mais confiavel que a
        # pagina do produto, que mistura numeros de outros blocos.
        o["estrelas_produto"] = info.get("estrelas")
        o["avaliacoes_produto"] = info.get("avaliacoes")
        if not o.get("estrelas"):
            o["estrelas"] = info.get("estrelas")
        if not o.get("avaliacoes"):
            o["avaliacoes"] = info.get("avaliacoes")
        if info.get("imagem"):
            o["imagem"] = info["imagem"]

        # referencia: prioriza a da pagina do produto; aceita a da busca so se o titulo confere
        ref = info.get("preco_referencia")
        if not ref and casa and ref_busca and ref_busca > info["preco"]:
            ref = ref_busca
        o["preco_referencia"] = ref if (ref and ref > info["preco"]) else None
        o["desconto_pct"] = (
            round((1 - o["preco"] / o["preco_referencia"]) * 100) if o["preco_referencia"] else None
        )
        o["verificado_em"] = agora

        # descartes
        motivos = []
        if not info["disponivel"]:
            motivos.append(f"indisponivel ({info['indisponivel_motivo']})")
        if not casa:
            motivos.append(f"titulo divergente (jaccard={jac})")
        if preco_busca and abs(info["preco"] - preco_busca) / max(preco_busca, 1) > 0.5:
            motivos.append(f"preco divergente busca R${preco_busca} vs produto R${info['preco']}")
        o["descartar"] = "; ".join(motivos) if motivos else None
        salvar(ofertas)

        flag = "DESCARTAR: " + o["descartar"] if o["descartar"] else "ok"
        print(f"  [{feitos}] {o['asin']}: R${o['preco']:.2f} "
              f"{'de R$%.2f' % o['preco_referencia'] if o['preco_referencia'] else 'sem ref'} "
              f"| {flag} | {info['titulo'][:40]}", file=sys.stderr)
        time.sleep(PAUSA)

    salvar(ofertas)
    ok = [o for o in ofertas if o.get("verificado_em") and o["verificado_em"] != "FALHA_FETCH" and not o.get("descartar")]
    faltam = [o for o in ofertas if not o.get("verificado_em")]
    print(f"\nverificadas agora: {feitos} | validas: {len(ok)} | faltam verificar: {len(faltam)}")


if __name__ == "__main__":
    main()
