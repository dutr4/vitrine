#!/bin/bash
# Atualizacao da vitrine: coleta, verifica, gera, valida e publica.
#
# Modos:
#   completo   (padrao) coleta candidatos, verifica, consolida, gera e publica.
#              Rodada pesada: 2x/dia.
#   publicados rodada leve: reconfere SO as ofertas que ja estao no ar (atualiza
#              preco, remove oferta vencida). Roda a cada 2h para a vitrine nunca
#              exibir preco velho.
#
# Uso: bash tools/pipeline.sh [completo|publicados] [--sem-deploy]
#
# Roda na VM do DEV (IP residencial, sem rate-limit severo) ou localmente.
# Publica na Oracle por SSH/rsync e (se configurado) faz commit+push no GitHub.
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ" || exit 1

export VITRINE_WORK="${VITRINE_WORK:-$HOME/.vitrine-work}"
export VITRINE_PAUSA="${VITRINE_PAUSA:-3}"
mkdir -p "$VITRINE_WORK"

MODO="completo"
DEPLOY=1
for arg in "$@"; do
  case "$arg" in
    completo|publicados) MODO="$arg" ;;
    --sem-deploy) DEPLOY=0 ;;
    *) echo "argumento desconhecido: $arg"; exit 2 ;;
  esac
done

LOG="$VITRINE_WORK/pipeline.log"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# trava: uma execucao por vez (o cron tambem usa flock)
exec 9>/tmp/vitrine.lock
if ! flock -n 9; then log "outra execucao em andamento — saindo"; exit 0; fi

# Buscas por categoria (o pool de candidatos)
QUERIES=(
  "air fryer" "panificadora" "cafeteira" "liquidificador" "batedeira" "micro-ondas"
  "frigobar" "aspirador de po" "ventilador" "purificador de agua"
  "lavadora de roupas" "maquina de lavar"
  "placa-mae am4" "fonte de alimentacao pc" "ssd nvme" "monitor gamer" "teclado mecanico"
  "furadeira" "parafusadeira"
)

log "===== INICIO (modo $MODO) ====="

# 0) sincroniza o repo (se for clone git)
if [ -d .git ]; then
  git pull --rebase --quiet 2>&1 | tee -a "$LOG" || log "aviso: git pull falhou (seguindo)"
fi

if [ "$MODO" = "publicados" ]; then
  # rodada leve: reconfere as ofertas que ja estao no ar
  log "modo publicados: reconferindo as ofertas publicadas..."
  python3 tools/refrescar_publicados.py 2>&1 | tail -14 | tee -a "$LOG"
else
  # 1) coleta de candidatos
  log "coletando candidatos (${#QUERIES[@]} buscas)..."
  python3 tools/coletar_ofertas.py busca "$VITRINE_WORK/ofertas_busca.json" "${QUERIES[@]}" 2>&1 | tail -3 | tee -a "$LOG"

  # 2) seleção (reaplica filtros, mantém o que já foi verificado, completa por categoria)
  log "montando seleção..."
  python3 tools/montar_selecao.py 18 2>&1 | tail -8 | tee -a "$LOG"

  # 3) verificação na página do produto (preço/disponibilidade reais)
  log "verificando ofertas na Amazon..."
  python3 tools/verificar_ofertas.py 90 2>&1 | tail -4 | tee -a "$LOG"
  python3 tools/verificar_destaques.py 6 2>&1 | tail -3 | tee -a "$LOG"

  # 4) consolidação (destaques + coletadas, com filtros de qualidade)
  log "consolidando..."
  python3 tools/consolidar.py 2>&1 | tail -12 | tee -a "$LOG"
fi

# 5) geração da seção de ofertas
log "gerando o site..."
python3 tools/gerar_site.py 2>&1 | tail -3 | tee -a "$LOG"

# 6) GATE: validação obrigatória antes de publicar
log "validando..."
if ! python3 tools/validar_site.py 2>&1 | tee -a "$LOG"; then
  log "ABORTADO: validação falhou — nada foi publicado"
  exit 1
fi

N_OFERTAS=$(grep -c 'class="card" data-asin' index.html || echo 0)
if [ "$N_OFERTAS" -lt 25 ]; then
  log "ABORTADO: apenas $N_OFERTAS ofertas válidas (mínimo 25) — nada foi publicado"
  exit 1
fi
log "ok: $N_OFERTAS ofertas válidas no site"

# 7) commit + push (versionamento)
if [ -d .git ]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git add -A
    git -c user.name=dutr4 -c user.email=contato@dutr4.com.br \
        commit -q -m "ofertas: atualização automática $(date '+%d/%m/%Y %H:%M') — $N_OFERTAS ofertas conferidas" 2>&1 | tee -a "$LOG"
    git push --quiet 2>&1 | tee -a "$LOG" && log "push ok" || log "aviso: push falhou"
  else
    log "sem mudanças para commitar"
  fi
fi

# 8) deploy na Oracle
if [ "$DEPLOY" = "1" ]; then
  log "publicando na Oracle..."
  if bash tools/deploy_oracle.sh 2>&1 | tail -5 | tee -a "$LOG"; then
    log "deploy ok"
  else
    log "ERRO: deploy falhou"
    exit 1
  fi
fi

log "===== FIM ($N_OFERTAS ofertas) ====="
