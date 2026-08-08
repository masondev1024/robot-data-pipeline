#!/usr/bin/env bash
# Validate host-only configuration without importing its values into this shell.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: prepare-public-demo.sh --env-file PATH

Validate the protected environment file required by the public PRISM demo.
EOF
}

error() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

is_bare_public_fqdn() {
  local domain=$1 label
  local ipv4_literal_pattern='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
  local -a labels

  [[ ${#domain} -le 253 && $domain == *.* && $domain != *[[:space:]]* ]] || return 1
  [[ ! $domain =~ $ipv4_literal_pattern ]] || return 1
  [[ $domain != .* && $domain != *. && $domain != *..* ]] || return 1

  IFS='.' read -r -a labels <<< "$domain"
  for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
    [[ $label =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  done
}

env_file=''
if [[ $# -eq 1 && $1 == '--help' ]]; then
  usage
  exit 0
fi
if [[ $# -eq 2 && $1 == '--env-file' ]]; then
  env_file=$2
else
  usage >&2
  exit 2
fi

[[ -n $env_file ]] || error 'an environment-file path is required'
[[ -f $env_file && ! -L $env_file ]] || error 'environment file must be a regular file'

file_mode=''
if stat --version >/dev/null 2>&1; then
  file_mode=$(stat -c '%a' "$env_file")
elif file_mode=$(stat -f '%Lp' "$env_file" 2>/dev/null); then
  :
else
  error 'unable to inspect environment-file permissions'
fi
[[ $file_mode == '600' ]] || error 'environment file must have mode 0600'

public_domain=''
caddy_acme_email=''
caddy_basic_auth_user=''
caddy_basic_auth_hash=''

while IFS= read -r line || [[ -n $line ]]; do
  line=${line%$'\r'}
  [[ -z $line || $line == \#* ]] && continue
  [[ $line == *=* ]] || error 'environment file contains an invalid line'

  key=${line%%=*}
  value=${line#*=}
  case $key in
    PUBLIC_DOMAIN) public_domain=$value ;;
    CADDY_ACME_EMAIL) caddy_acme_email=$value ;;
    CADDY_BASIC_AUTH_USER) caddy_basic_auth_user=$value ;;
    CADDY_BASIC_AUTH_HASH) caddy_basic_auth_hash=$value ;;
  esac
done < "$env_file"

[[ -n $public_domain ]] || error 'PUBLIC_DOMAIN is required'
[[ -n $caddy_acme_email ]] || error 'CADDY_ACME_EMAIL is required'
[[ -n $caddy_basic_auth_user ]] || error 'CADDY_BASIC_AUTH_USER is required'
[[ -n $caddy_basic_auth_hash ]] || error 'CADDY_BASIC_AUTH_HASH is required'
is_bare_public_fqdn "$public_domain" || error 'PUBLIC_DOMAIN must be a bare public FQDN'

if [[ ${#caddy_basic_auth_hash} -ge 2 && ${caddy_basic_auth_hash:0:1} == "'" && ${caddy_basic_auth_hash: -1} == "'" ]]; then
  caddy_basic_auth_hash=${caddy_basic_auth_hash:1:${#caddy_basic_auth_hash}-2}
  [[ $caddy_basic_auth_hash != *"'"* ]] || error 'CADDY_BASIC_AUTH_HASH must have one balanced surrounding single-quote pair'
elif [[ $caddy_basic_auth_hash == *"'"* ]]; then
  error 'CADDY_BASIC_AUTH_HASH has unbalanced single quotes'
else
  error "CADDY_BASIC_AUTH_HASH must be single-quoted as '\$2b\$...'"
fi
[[ $caddy_basic_auth_hash =~ ^\$2[aby]\$(0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}$ ]] || error 'CADDY_BASIC_AUTH_HASH must be a complete bcrypt hash'

printf 'Validated public demo environment file: %s\n' "$env_file"
printf 'Validated public domain: %s\n' "$public_domain"
