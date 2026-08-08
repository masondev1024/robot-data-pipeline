#!/usr/bin/env bash
# Recreate only the deterministic public-demo data volume after explicit consent.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: reset-public-demo-data.sh --env-file PATH --confirm-reset RESET_PRISM_PUBLIC_DEMO_DATA

Stop the public operator app, recreate its named data volume, and wait for it
to become healthy again. This intentionally removes prism-public-data.
EOF
}

error() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

env_file=''
confirmation=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --help)
      [[ $# -eq 1 ]] || error '--help cannot be combined with other options'
      usage
      exit 0
      ;;
    --env-file)
      [[ $# -ge 2 && -z $env_file ]] || error '--env-file requires one path'
      env_file=$2
      shift 2
      ;;
    --confirm-reset)
      [[ $# -ge 2 && -z $confirmation ]] || error '--confirm-reset requires one phrase'
      confirmation=$2
      shift 2
      ;;
    *)
      error "unknown option: $1"
      ;;
  esac
done

[[ -n $env_file ]] || error '--env-file is required'
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
compose_file="$script_dir/../docker-compose.public.yml"

bash "$script_dir/prepare-public-demo.sh" --env-file "$env_file"

[[ $confirmation == 'RESET_PRISM_PUBLIC_DEMO_DATA' ]] || error 'reset requires --confirm-reset RESET_PRISM_PUBLIC_DEMO_DATA'

docker compose --env-file "$env_file" -f "$compose_file" stop operator-app
docker compose --env-file "$env_file" -f "$compose_file" rm -f operator-app
docker volume rm prism-public-data
docker compose --env-file "$env_file" -f "$compose_file" up -d --no-build --wait
