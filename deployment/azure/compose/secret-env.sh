#!/bin/sh
# Production-only entrypoint shim (docker-compose.azure.yml, ADR-048).
#
# The application images read their credentials from environment variables. In Azure those values
# must not appear in `docker inspect` or the Compose model, so Compose mounts each credential as a
# file under /run/secrets (rendered from Key Vault by the VM's managed identity) and this shim
# exports them into the application process only, then replaces itself with the image command.
#
# PROPERTYSCOPE_SECRET_ENV lists "VARIABLE=secret_name" pairs separated by spaces. It contains
# names only, never values.
set -eu

for pair in ${PROPERTYSCOPE_SECRET_ENV:-}; do
    variable=${pair%%=*}
    secret=${pair#*=}
    case "$variable" in
        '' | *[!A-Z0-9_]*)
            echo "secret-env: invalid variable name in PROPERTYSCOPE_SECRET_ENV" >&2
            exit 64
            ;;
    esac
    case "$secret" in
        '' | *[!a-z0-9_-]*)
            echo "secret-env: invalid secret name for $variable" >&2
            exit 64
            ;;
    esac
    file="/run/secrets/$secret"
    if [ ! -r "$file" ]; then
        echo "secret-env: $variable needs the Compose secret $secret, which is not mounted" >&2
        exit 66
    fi
    value=$(cat "$file")
    if [ -z "$value" ]; then
        echo "secret-env: Compose secret $secret is empty" >&2
        exit 65
    fi
    export "$variable=$value"
done
unset PROPERTYSCOPE_SECRET_ENV pair variable secret file value

exec "$@"
