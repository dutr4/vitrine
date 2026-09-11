#!/bin/bash
# Publica a vitrine na Oracle (backup -> staging -> rsync no web root).
# Roda em Linux (VM do DEV) ou em qualquer host com ssh/scp/rsync.
#
# Variaveis de ambiente (com padroes):
#   ORACLE_HOST   146.235.48.14
#   ORACLE_USER   ubuntu
#   ORACLE_KEY    ~/.ssh/oracle_deploy
#   ORACLE_WWW    /var/www/vitrine.dutr4.com.br
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${ORACLE_HOST:-146.235.48.14}"
USUARIO="${ORACLE_USER:-ubuntu}"
KEY="${ORACLE_KEY:-$HOME/.ssh/oracle_deploy}"
WWW="${ORACLE_WWW:-/var/www/vitrine.dutr4.com.br}"
STAGE="/home/${USUARIO}/vitrine-novo"
TARBALL="$(mktemp -t vitrine-upload-XXXXXX.tgz)"
OPTS=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
ALVO="${USUARIO}@${HOST}"

echo "== backup no servidor =="
ssh "${OPTS[@]}" "$ALVO" \
  "sudo tar -czf /home/${USUARIO}/vitrine-pre-\$(date +%F_%H%M%S).tar.gz -C /var/www vitrine.dutr4.com.br && echo backup_ok" || exit 1

echo "== staging =="
ssh "${OPTS[@]}" "$ALVO" "rm -rf $STAGE && mkdir -p $STAGE && echo staging_ok" || exit 1

echo "== empacotando (sem .git, tools/, dados/) =="
cd "$RAIZ" || exit 1
tar -czf "$TARBALL" --exclude=./.git --exclude=./tools --exclude=./dados --exclude=./.github . || exit 1

echo "== upload =="
scp "${OPTS[@]}" "$TARBALL" "$ALVO:$STAGE/" || { rm -f "$TARBALL"; exit 1; }

echo "== aplicando no web root =="
ssh "${OPTS[@]}" "$ALVO" \
  "cd $STAGE && tar -xzf $(basename "$TARBALL") && rm $(basename "$TARBALL") && \
   sudo rsync -a --delete $STAGE/ $WWW/ && \
   sudo chown -R root:root $WWW && \
   sudo find $WWW -type d -exec chmod 755 {} + && sudo find $WWW -type f -exec chmod 644 {} + && \
   echo deploy_ok" || { rm -f "$TARBALL"; exit 1; }

rm -f "$TARBALL"
echo "deploy concluido"
