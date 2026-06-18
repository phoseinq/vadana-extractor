#!/usr/bin/env bash
# vadana — download recordings + manage the Vadana bot service
SERVICE=vadana-bot
DIR=/opt/vadana-extractor
ENVF="$DIR/bot/.env"
PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3

dl() {
  local type="$1" url="$2"
  [ -n "$url" ] || read -rp "  recording URL: " url
  [ -n "$url" ] || { echo "no URL"; return 1; }
  ( cd "$DIR" && case "$type" in
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
        && systemctl restart "$SERVICE" && echo "✓ updated + restarted" ;;
    status)  systemctl status "$SERVICE" --no-pager ;;
    logs)    journalctl -u "$SERVICE" -f ;;
    start)   systemctl start "$SERVICE"   && echo "✓ started" ;;
    stop)    systemctl stop "$SERVICE"    && echo "✓ stopped" ;;
    restart) systemctl restart "$SERVICE" && echo "✓ restarted" ;;
    env)     "${EDITOR:-nano}" "$ENVF" && systemctl restart "$SERVICE" && echo "✓ saved + restarted" ;;
    uninstall)
      read -rp "Remove the systemd service? [y/N] " a
      [ "$a" = y ] || { echo "cancelled"; return; }
      systemctl disable --now "$SERVICE" 2>/dev/null
      rm -f "/etc/systemd/system/$SERVICE.service"; systemctl daemon-reload
      read -rp "Also delete cache/, logs/, bot_work/ (file_id store, quotas, scratch)? [y/N] " b
      [ "$b" = y ] && rm -rf "$DIR/cache" "$DIR/logs" "$DIR/bot_work" && echo "✓ data removed"
      echo "✓ uninstalled" ;;
    *) return 1 ;;
  esac
}

menu() {
  while true; do
    st=$(systemctl is-active "$SERVICE" 2>/dev/null || echo "n/a")
    printf '\n  \033[1;36mVadana\033[0m  ·  service: %s\n' "$st"
    echo "  download   1) files     2) whiteboard PDF   3) video"
    echo "  service    4) status    5) logs      6) restart"
    echo "             7) start     8) stop       9) update"
    echo "            10) edit env  11) uninstall  0) exit"
    read -rp "  > " n
    case "$n" in
      1) dl files ;; 2) dl whiteboard ;; 3) dl video ;;
      4) run status ;; 5) run logs ;; 6) run restart ;;
      7) run start ;; 8) run stop ;; 9) run update ;;
      10) run env ;; 11) run uninstall ;; 0|q|"") exit 0 ;;
    esac
  done
}

[ -z "$1" ] && menu || run "$@" || { echo "unknown command: $1"; exit 1; }
