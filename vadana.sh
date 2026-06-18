#!/usr/bin/env bash
# vadana — download recordings + manage the Vadana bot service
SERVICE=vadana-bot
DIR=/opt/vadana-extractor
ENVF="$DIR/bot/.env"
PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3

C=$'\033[1;36m'; G=$'\033[1;32m'; R=$'\033[1;31m'; Y=$'\033[1;33m'
D=$'\033[2m'; B=$'\033[1m'; N=$'\033[0m'

pause() { printf "\n   ${D}press Enter to go back…${N}"; read -r _; }

dl() {
  local type="$1" url="$2"
  [ -n "$url" ] || { printf "   ${C}›${N} paste the recording link: "; read -r url; }
  [ -n "$url" ] || { echo "   no link given."; return 1; }
  ( cd "$DIR" || exit 1
    set -a; [ -f "$ENVF" ] && . "$ENVF"; set +a   # picks up IRAN_PROXY when hosting abroad
    case "$type" in
      files)      "$PY" download_slides.py "$url" ;;
      whiteboard) "$PY" make_video.py "$url" --pages-only ;;
      video)      "$PY" make_video.py "$url" ;;
    esac )
}

run() {
  case "$1" in
    files)          dl files "$2" ;;
    whiteboard|wb)  dl whiteboard "$2" ;;
    video)          dl video "$2" ;;
    update)
      cd "$DIR" && git pull --ff-only \
        && "$DIR/venv/bin/pip" install -q -r requirements.txt -r bot/requirements.txt \
        && systemctl restart "$SERVICE" && echo "updated + restarted" ;;
    status)  systemctl status "$SERVICE" --no-pager ;;
    logs)    journalctl -u "$SERVICE" -f ;;
    start)   systemctl start "$SERVICE"   && echo "started" ;;
    stop)    systemctl stop "$SERVICE"    && echo "stopped" ;;
    restart) systemctl restart "$SERVICE" && echo "restarted" ;;
    env)     "${EDITOR:-nano}" "$ENVF" && systemctl restart "$SERVICE" && echo "saved + restarted" ;;
    uninstall)
      read -rp "Remove the systemd service? [y/N] " a
      [ "$a" = y ] || { echo "cancelled"; return; }
      systemctl disable --now "$SERVICE" 2>/dev/null
      rm -f "/etc/systemd/system/$SERVICE.service"; systemctl daemon-reload
      read -rp "Also delete cache/, logs/, bot_work/? [y/N] " b
      [ "$b" = y ] && rm -rf "$DIR/cache" "$DIR/logs" "$DIR/bot_work" && echo "data removed"
      echo "uninstalled" ;;
    *) echo "unknown command: $1" >&2; return 2 ;;
  esac
}

menu() {
  local st dot n
  while true; do
    clear 2>/dev/null
    st=$(systemctl is-active "$SERVICE" 2>/dev/null || echo "n/a")
    case "$st" in
      active) dot="${G}●${N}" ;;
      inactive|failed) dot="${R}●${N}" ;;
      *) dot="${Y}●${N}" ;;
    esac
    printf "\n   ${C}■${N} ${B}Vadana${N} ${D}· recordings extractor${N}\n"
    printf "   service ${dot} %s\n\n" "$st"
    printf "   ${D}download${N}\n"
    printf "     ${C}1${N} shared files      ${C}2${N} whiteboard PDF      ${C}3${N} archive video\n\n"
    printf "   ${D}service${N}\n"
    printf "     ${C}4${N} status   ${C}5${N} logs   ${C}6${N} restart   ${C}7${N} start   ${C}8${N} stop   ${C}9${N} update\n\n"
    printf "     ${C}e${N} edit config      ${C}u${N} uninstall      ${C}q${N} quit\n\n"
    printf "   ${C}›${N} "
    read -r n || break
    case "$n" in
      1) dl files; pause ;; 2) dl whiteboard; pause ;; 3) dl video; pause ;;
      4) run status; pause ;; 5) run logs ;; 6) run restart; pause ;;
      7) run start; pause ;; 8) run stop; pause ;; 9) run update; pause ;;
      e|E) run env; pause ;; u|U) run uninstall; pause ;;
      q|Q|0|"") clear 2>/dev/null; exit 0 ;;
      *) ;;
    esac
  done
}

[ -z "$1" ] && menu || run "$@"
