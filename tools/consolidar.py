#!/usr/bin/env python3
"""Consolida dados/ofertas.json: destaques da curadoria original + ofertas coletadas.

Fontes:
  dados/destaques.json          (curadoria original, com nota editorial e guia)
  /tmp/selecao_verificada.json  (ofertas coletadas e verificadas)

Regras: apenas ofertas disponiveis, com preco, nao descartadas. Destaques tem
prioridade (mantem nota/guia) e entram como oferta normal na sua categoria.

Uso: python3 tools/consolidar.py
"""
import json
import os
import unicodedata

# Diretorio de trabalho (arquivos intermediarios). Sobrescreva com VITRINE_WORK.
WORK = os.environ.get("VITRINE_WORK", "/tmp")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTAQUES = os.path.join(RAIZ, "dados", "destaques.json")
SELECAO = f"{WORK}/selecao_verificada.json"
SAIDA = os.path.join(RAIZ, "dados", "ofertas.json")

MAPA_CAT = {
    "utilidades": "Casa & Utilidades",
    "refrigeracao": "Casa & Utilidades",
    "refrigeração": "Casa & Utilidades",
    "hardware": "Informática",
    "informatica": "Informática",
    "informática": "Informática",
    "cozinha": "Cozinha",
    "lavanderia": "Lavanderia",
    "casa & utilidades": "Casa & Utilidades",
    "ferramentas & automotivo": "Ferramentas & Automotivo",
    "casa inteligente & audio": "Casa Inteligente & Áudio",
}


def norm_cat(c: str | None) -> str | None:
    if not c:
        return None
    k = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode().lower().strip()
    return MAPA_CAT.get(k, c)


def valida(o: dict) -> bool:
    return bool(o.get("preco") and o.get("disponivel") and not o.get("descartar"))


# Divergencia maxima aceitavel entre o preco do card de busca e o preco da pagina
# do produto. Acima disso, o anuncio provavelmente e de outra variante/acessorio.
DIVERGENCIA_MAX = 0.35

# Modelos duplicados revisados a mao (mesmo produto listado duas vezes):
# mantemos apenas um anuncio por modelo.
BLACKLIST = {
    "B0D9YSWZ8T",  # Samsung WW11T Inox 11kg duplicado (fica B0D9YS13X6, mais avaliacoes)
    "B0CY6T3B68",  # WAP WF-700K10 duplicado (fica B0CYCJ66Y8, mais barato)
}


def titulo_chave(t: str) -> str:
    return " ".join((t or "").lower().split())


def dedupe(lst: list[dict]) -> tuple[list[dict], list[str]]:
    """Remove duplicatas exatas de titulo (mantendo mais avaliacoes) e a blacklist."""
    por_titulo: dict[str, dict] = {}
    removidos = []
    for o in lst:
        if o["asin"] in BLACKLIST:
            removidos.append(f"{o['asin']} (duplicata de modelo, revisado a mao)")
            continue
        k = titulo_chave(o.get("titulo") or "")
        atual = por_titulo.get(k)
        if atual is None:
            por_titulo[k] = o
            continue
        # mantem o com mais avaliacoes
        if (o.get("avaliacoes") or 0) > (atual.get("avaliacoes") or 0):
            removidos.append(f"{atual['asin']} (titulo identico; mantido {o['asin']})")
            por_titulo[k] = o
        else:
            removidos.append(f"{o['asin']} (titulo identico; mantido {atual['asin']})")
    return list(por_titulo.values()), removidos


def checa_divergencia(o: dict, brutos: dict) -> str | None:
    """Devolve motivo se o preco da pagina do produto divergir demais do card de busca."""
    if o.get("origem") != "coleta":
        return None
    b = brutos.get(o["asin"])
    if not b or not b.get("preco") or not o.get("preco"):
        return None
    pb, pp = b["preco"], o["preco"]
    div = abs(pp - pb) / pb
    if div > DIVERGENCIA_MAX:
        return f"preco da pagina (R${pp:.2f}) divergente do card de busca (R${pb:.2f}): {div*100:.0f}%"
    return None


def main() -> None:
    finais: dict[str, dict] = {}

    # Avaliacoes/estrelas: o card da busca (listagem) e mais confiavel que a pagina
    # do produto. Restaura os valores da busca para cada ASIN.
    brutos = {}
    if os.path.exists(f"{WORK}/ofertas_busca.json"):
        for b in json.load(open(f"{WORK}/ofertas_busca.json", encoding="utf-8"))["ofertas"]:
            brutos.setdefault(b["asin"], b)


    # 1) destaques (curadoria original) primeiro
    if os.path.exists(DESTAQUES):
        d = json.load(open(DESTAQUES, encoding="utf-8"))
        n = 0
        for it in d.get("itens", []):
            if not valida(it):
                continue
            it = dict(it)
            it["categoria"] = norm_cat(it.get("categoria_original")) or "Ofertas"
            it["titulo"] = it.get("titulo_produto") or it.get("titulo_site")
            it["origem"] = "curadoria"
            b = brutos.get(it["asin"], {})
            if b.get("estrelas"):
                it["estrelas"] = b["estrelas"]
            if b.get("avaliacoes"):
                it["avaliacoes"] = b["avaliacoes"]
            finais[it["asin"]] = it
            n += 1
        print(f"destaques validos: {n} de {len(d.get('itens', []))}")

    # 2) ofertas coletadas
    if os.path.exists(SELECAO):
        s = json.load(open(SELECAO, encoding="utf-8"))
        n = 0
        for o in s.get("ofertas", []):
            if not valida(o) or o["asin"] in finais:
                continue
            o = dict(o)
            o["categoria"] = norm_cat(o.get("categoria")) or "Ofertas"
            o["titulo"] = o.get("titulo_produto") or o.get("titulo")
            o["origem"] = "coleta"
            b = brutos.get(o["asin"], {})
            if b.get("estrelas"):
                o["estrelas"] = b["estrelas"]
            if b.get("avaliacoes"):
                o["avaliacoes"] = b["avaliacoes"]
            finais[o["asin"]] = o
            n += 1
        print(f"ofertas coletadas validas: {n}")

    lst = list(finais.values())

    # filtro de divergencia de preco (risco de variante/acessorio errado)
    aprovadas, descartadas = [], []
    for o in lst:
        motivo = checa_divergencia(o, brutos)
        if motivo:
            descartadas.append(f"{o['asin']} — {motivo}")
            continue
        aprovadas.append(o)

    # duplicatas de titulo + blacklist de modelos repetidos
    aprovadas, dups = dedupe(aprovadas)
    lst = aprovadas

    if descartadas:
        print(f"\ndescartadas por divergencia de preco ({len(descartadas)}):")
        for d in descartadas:
            print(f"  {d}")
    if dups:
        print(f"\nduplicatas removidas ({len(dups)}):")
        for d in dups:
            print(f"  {d}")

    from collections import Counter
    print(f"\ntotal consolidado: {len(lst)}")
    for cat, qtd in Counter(o["categoria"] for o in lst).most_common():
        print(f"  {cat}: {qtd}")
    com_desc = [o for o in lst if o.get("desconto_pct")]
    print(f"  com desconto exibivel: {len(com_desc)}")
    print(f"  com nota editorial: {len([o for o in lst if o.get('nota')])}")

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    json.dump({"gerado_em": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
               "total": len(lst), "ofertas": lst},
              open(SAIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nsalvo: {SAIDA}")


if __name__ == "__main__":
    main()
