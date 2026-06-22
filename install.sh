#!/usr/bin/env bash
# Vadana bot — one-command install. Downloads, sets up, and starts the bot.
#   curl -fsSL https://raw.githubusercontent.com/phoseinq/vadana-extractor/main/install.sh | bash
set -euo pipefail
DIR=/opt/vadana-extractor
REPO=https://github.com/phoseinq/vadana-extractor.git

ask() {                              # ask "prompt" [default] -> echoes the answer
  local val=""
  if [ -e /dev/tty ]; then printf '%s' "$1" >/dev/tty; read -r val </dev/tty || true; fi
  printf '%s' "${val:-${2:-}}"
}

fetch_code() {
  if [ -f "$DIR/requirements.txt" ]; then git -C "$DIR" pull --ff-only || true
  else git clone "$REPO" "$DIR"; fi
}

write_env() {                        # create bot/.env from answers (keep an existing one)
  if [ -f bot/.env ]; then TOKEN_SET=1; return; fi
  cp bot/.env.example bot/.env
  local token admins
  token=$(ask 'BOT_TOKEN (from @BotFather): ')
  admins=$(ask 'ADMINS — your numeric user id(s), comma-separated (Enter to skip): ')
  if [ -n "$token" ]; then sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$token|" bot/.env; TOKEN_SET=1; else TOKEN_SET=0; fi
  if [ -n "$admins" ]; then sed -i "s|^ADMINS=.*|ADMINS=$admins|" bot/.env; fi
}

native() {
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip ffmpeg git
  fetch_code; cd "$DIR"
  python3 -m venv venv
  venv/bin/pip install -qU pip
  venv/bin/pip install -q -r requirements.txt -r bot/requirements.txt
  write_env
  install -m 755 vadana.sh /usr/local/bin/vadana
  cp bot/systemd/vadana-bot.service /etc/systemd/system/
  systemctl daemon-reload
  if [ "${TOKEN_SET:-0}" = 1 ]; then
    systemctl enable --now vadana-bot
    echo "✓ running.  logs: journalctl -u vadana-bot -f"
  else
    systemctl enable vadana-bot
    echo "Set BOT_TOKEN:  vadana env   then it starts."
  fi
}

docker_mode() {
  command -v docker >/dev/null || { echo "Docker isn't installed — https://docs.docker.com/engine/install/"; exit 1; }
  apt-get install -y -q git
  fetch_code; cd "$DIR"
  install -m 755 vadana.sh /usr/local/bin/vadana   # the manage CLI works in docker mode too
  write_env
  if [ "${TOKEN_SET:-0}" = 1 ]; then
    printf 'pulling the bot image…\n'
    if docker compose pull --quiet 2>/dev/null; then docker compose up -d
    else printf 'no prebuilt image — building locally…\n'; docker compose up -d --build; fi
    echo "✓ running.  logs: docker compose logs -f"
  else
    echo "Set BOT_TOKEN in bot/.env, then:  docker compose pull && docker compose up -d"
  fi
}

# one prompt picks the method (or pass: install.sh docker | install.sh native)
case "$(printf '%s' "${1:-$(ask 'Install with Docker? [y/N]: ' n)}" | tr '[:upper:]' '[:lower:]')" in
  y|yes|d|docker) docker_mode ;;
  *)              native ;;
esac
