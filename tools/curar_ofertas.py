"""Curadoria: filtra o pool bruto e monta a selecao por categoria."""
import json
import os, re, unicodedata
from collections import defaultdict

# Diretorio de trabalho (arquivos intermediarios). Sobrescreva com VITRINE_WORK.
WORK = os.environ.get("VITRINE_WORK", "/tmp")

RAW = f"{WORK}/ofertas_busca.json"

CATEGORIAS = {
    "Cozinha": [
        "air fryer", "fritadeira", "panificadora", "cafeteira", "cafeteira expresso",
        "liquidificador", "batedeira", "micro-ondas", "microondas", "churrasqueira",
        "cooktop", "fogao", "forno", "multiprocessador", "mixer", "sanduicheira",
        "grill", "pipoqueira", "chaleira", "jarra eletrica", "processador de alimentos",
        "panela eletrica", "espagueteira", "moedor",
    ],
    "Lavanderia": [
        "lavadora", "maquina de lavar", "tanquinho", "ferro de passar", "secadora",
        "lava e seca", "centrifuga",
    ],
    "Casa & Utilidades": [
        "frigobar", "geladeira", "aspirador", "ventilador", "purificador", "ar-condicionado",
        "ar condicionado", "umidificador", "climatizador", "circulador", "robo aspirador",
        "roborock", "cortina", "jogo de lencois", "rack", "guarda-roupa", "colchao",
        "cafeteira", "adega", "bebedouro", "air cooler",
    ],
    "Informática": [
        "placa-mae", "placa mae", "fonte", "ssd", "hd externo", "hd interno",
        "memoria ram", "memoria ddr", "pente de memoria", "memoria 8gb", "memoria 16gb",
        "monitor", "teclado", "mouse", "headset", "gabinete", "cooler", "water cooler",
        "processador", "ryzen", "intel core", "notebook", "webcam", "roteador", "hub usb",
        "impressora", "cartao de memoria", "pen drive", "estabilizador", "nobreak",
        "cadeira gamer", "placa de video",
    ],
    "Ferramentas & Automotivo": [
        "furadeira", "parafusadeira", "esmerilhadeira", "serra", "kit de ferramentas",
        "chave de fenda", "trena", "multimetro", "compresso", "lavadora de alta pressao",
        "aspirador de po automotivo", "carregador de bateria",
    ],
    "Casa Inteligente & Áudio": [
        "echo dot", "alexa", "lampada inteligente", "lampada smart", "camera wifi",
        "fechadura digital", "tomada inteligente", "caixa de som", "soundbar", "fone de ouvido",
        "headphone", "echo show", "chromecast", "fire tv stick",
    ],
}


def sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


# Nada de livros/e-books/midia na vitrine: o site e de produtos.
BLOQUEIO = [
    "capa comum", "capa dura", "ebook", "e-book", "kindle", "edicao portugues",
    "portuguese edition", "papel", "capa flexivel", "brochura", "livro", "revista",
    "dvd", "blu-ray", "cd de audio", "jogo para", "baralho", "carta para",
]
PRECO_MINIMO = 40.0


def bloqueado(titulo: str) -> bool:
    t = sem_acento(titulo)
    return any(b in t for b in BLOQUEIO)


def categorizar(titulo: str) -> str | None:
    t = sem_acento(titulo)
    for cat, chaves in CATEGORIAS.items():
        for k in chaves:
            if sem_acento(k) in t:
                return cat
    return None


def main() -> None:
    dados = json.load(open(RAW, encoding="utf-8"))
    ofertas = dados["ofertas"]
    print(f"pool bruto: {len(ofertas)}")

    vistos, unicas = set(), []
    for o in ofertas:
        if o["asin"] in vistos:
            continue
        vistos.add(o["asin"])
        unicas.append(o)
    print(f"unicas por ASIN: {len(unicas)}")

    boas = []
    for o in unicas:
        if o.get("patrocinado"):
            continue
        if not o.get("preco") or not o.get("preco_referencia"):
            continue
        if not o.get("titulo") or bloqueado(o["titulo"]):
            continue
        if o["preco"] < PRECO_MINIMO:
            continue
        desc = (1 - o["preco"] / o["preco_referencia"]) * 100
        if desc < 12:
            continue
        cat = categorizar(o["titulo"])
        if not cat:
            continue
        o["desconto_pct"] = round(desc)
        o["categoria"] = cat
        boas.append(o)

    print(f"com desconto real >=12%, nao patrocinadas, categoria identificada: {len(boas)}")

    por_cat = defaultdict(list)
    for o in boas:
        por_cat[o["categoria"]].append(o)

    print("\n=== por categoria (antes do corte de qualidade) ===")
    for cat, lst in sorted(por_cat.items(), key=lambda x: -len(x[1])):
        com_aval = [x for x in lst if (x.get("avaliacoes") or 0) >= 50 and (x.get("estrelas") or 0) >= 4.0]
        print(f"  {cat}: {len(lst)} | com >=50 avaliacoes e >=4.0 estrelas: {len(com_aval)}")

    # selecao final: prioriza desconto + volume de avaliacoes
    selecao = []
    for cat, lst in por_cat.items():
        bons = [x for x in lst if (x.get("avaliacoes") or 0) >= 30 and (x.get("estrelas") or 0) >= 4.0]
        bons.sort(key=lambda x: -(x["desconto_pct"] * min(x["avaliacoes"], 5000) ** 0.35))
        selecao.extend(bons[:12])

    print(f"\n=== SELECAO PRELIMINAR: {len(selecao)} ===")
    for o in sorted(selecao, key=lambda x: (x["categoria"], -x["desconto_pct"])):
        print(f"  [{o['categoria'][:14]:14}] {o['desconto_pct']:2}% | R${o['preco']:>8.2f} (de R${o['preco_referencia']:.2f}) | "
              f"{o['estrelas']}*({o['avaliacoes']}) | {o['titulo'][:44]}")

    json.dump({"total": len(selecao), "ofertas": selecao}, open("/tmp/selecao.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\nsalvo: /tmp/selecao.json")


if __name__ == "__main__":
    main()
