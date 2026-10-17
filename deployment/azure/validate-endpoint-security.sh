#!/usr/bin/env bash
# Endpoint-security validation for the Azure deployment (bonus R2-B5, ADR-048).
#
# Black-box checks from outside the VM, exactly as an internet client sees the service:
#   TLS with a publicly trusted certificate, no TLS 1.0/1.1, a permanent HTTP -> HTTPS redirect,
#   HSTS and security headers, no server version disclosure, 401 on operations/AI routes
#   without operator credentials, 429 from the nginx rate limits, and closed SSH/database/AI/
#   development ports. With Azure access it also reads the NSG (read-only).
#
# Usage: deploy.sh validate-endpoint    (or set PUBLIC_FQDN and run this script directly)
# Optional: EDGE_USER / EDGE_PASSWORD   also prove that valid operator credentials pass Caddy
#           AZURE_RESOURCE_GROUP        enables the NSG rule check
#           LOG_DIR                     where endpoint-security.txt is written
#           EDGE_CA_FILE                CA certificates (root and intermediate) to trust for every
#                                       check except the publicly-trusted-certificate one: Caddy's
#                                       internal CA in the local rehearsal, so the HTTP-level
#                                       checks still run
set -uo pipefail

HOST=${PUBLIC_FQDN:?PUBLIC_FQDN is required, e.g. propertyscope-nsw-g20.australiaeast.cloudapp.azure.com}
BASE="https://${HOST}"
OUTPUT_DIR=${LOG_DIR:-.}
REPORT="$OUTPUT_DIR/endpoint-security.txt"
FAILURES=0
TLS_OPTIONS=()
if [[ -n ${EDGE_CA_FILE:-} ]]; then
    [[ -s $EDGE_CA_FILE ]] || {
        echo "EDGE_CA_FILE $EDGE_CA_FILE is empty or missing" >&2
        exit 2
    }
    # A private CA publishes no revocation list; Windows (Schannel) curl would otherwise refuse
    # it. With Schannel the file must also hold the intermediate certificate.
    TLS_OPTIONS=(--cacert "$EDGE_CA_FILE" --ssl-no-revoke)
fi
mkdir -p "$OUTPUT_DIR"
: >"$REPORT"

result() {
    local verdict=$1
    shift
    printf '%s %s\n' "$verdict" "$*" | tee -a "$REPORT"
    if [[ $verdict == FAIL ]]; then
        FAILURES=$((FAILURES + 1))
    fi
}

expect() {
    local description=$1 actual=$2 pattern=$3
    if [[ $actual =~ $pattern ]]; then
        result PASS "$description ($actual)"
    else
        result FAIL "$description (got: ${actual:-nothing})"
    fi
}

# Every check but the public-trust one: trusts EDGE_CA_FILE when it is set.
edge_curl() {
    curl "${TLS_OPTIONS[@]}" "$@"
}

status_of() {
    edge_curl --silent --output /dev/null --max-time 15 --write-out '%{http_code}' "$@" || true
}

echo "Endpoint security validation for ${BASE} at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$REPORT"
if ((${#TLS_OPTIONS[@]})); then
    result INFO "HTTP-level checks trust EDGE_CA_FILE; the public-trust check below never does"
fi

# --- TLS -------------------------------------------------------------------------------------
# The system trust store only: no EDGE_CA_FILE and no CA override from the environment.
if env -u CURL_CA_BUNDLE -u SSL_CERT_FILE curl --silent --show-error --fail --output /dev/null \
    --max-time 15 "$BASE/healthz" 2>/dev/null; then
    result PASS "HTTPS serves a publicly trusted certificate for $HOST"
else
    result FAIL "HTTPS certificate is not trusted (or the edge is down) for $HOST"
fi
issuer=$(edge_curl --silent --verbose --output /dev/null --max-time 15 "$BASE/healthz" 2>&1 | sed -n 's/^\*  issuer: //p' | head -n 1)
[[ -n $issuer ]] && result INFO "certificate issuer: $issuer"
# A refused handshake (000) proves something only while TLS 1.2+ is answered on the same URL.
legacy=$(status_of --tlsv1.1 --tls-max 1.1 "$BASE/healthz")
modern=$(status_of --tlsv1.2 "$BASE/healthz")
expect "TLS 1.1 and older are refused while TLS 1.2+ is served" "tls<=1.1:$legacy tls>=1.2:$modern" '^tls<=1\.1:000 tls>=1\.2:200$'

# --- HTTP -> HTTPS ---------------------------------------------------------------------------
redirect=$(curl --silent --output /dev/null --max-time 15 --write-out '%{http_code} %{redirect_url}' "http://${HOST}/features/data-platform/" || true)
expect "HTTP permanently redirects to HTTPS" "$redirect" "^(301|308) https://${HOST//./\\.}/features/data-platform/$"

# --- Headers ---------------------------------------------------------------------------------
headers=$(edge_curl --silent --dump-header - --output /dev/null --max-time 15 "$BASE/" | tr -d '\r' | tr '[:upper:]' '[:lower:]')
expect "HSTS for at least one year" "$(grep '^strict-transport-security:' <<<"$headers")" 'max-age=(3153[6-9][0-9]{3}|[4-9][0-9]{7}|[0-9]{9,})'
expect "X-Content-Type-Options nosniff" "$(grep '^x-content-type-options:' <<<"$headers" | head -n 1)" 'nosniff'
expect "Framing denied" "$(grep -E '^(x-frame-options|content-security-policy):' <<<"$headers" | tr '\n' ' ')" "(x-frame-options: deny|frame-ancestors 'none')"
expect "Content-Security-Policy present" "$(grep '^content-security-policy:' <<<"$headers")" "default-src 'self'"
expect "Referrer-Policy present" "$(grep '^referrer-policy:' <<<"$headers" | head -n 1)" 'same-origin|no-referrer'
server=$(grep '^server:' <<<"$headers" || true)
if [[ -z $server || ! $server =~ [0-9]+\.[0-9]+ ]]; then
    result PASS "no server version disclosed (${server:-no Server header})"
else
    result FAIL "server version disclosed: $server"
fi

# --- Authentication on operations and AI routes ----------------------------------------------
for path in /operations/ai-mode/ /api/ai-mode/runs /api/v1/runs /api/data-platform/v1/artifact-retention \
    /api/data-platform/v1/release-reviews /api/market-intelligence/v1/assistant/turns; do
    code=$(status_of "$BASE$path")
    expect "anonymous $path requires operator credentials" "$code" '^401$'
done
challenge=$(edge_curl --silent --dump-header - --output /dev/null --max-time 15 "$BASE/operations/ai-mode/" | tr -d '\r' | grep -i '^www-authenticate:' || true)
expect "401 carries a Basic challenge" "$challenge" '[Bb]asic'
code=$(status_of --user "intruder:wrong-password" "$BASE/operations/ai-mode/")
expect "wrong operator credentials are rejected" "$code" '^401$'
if [[ -n ${EDGE_PASSWORD:-} ]]; then
    code=$(status_of --user "${EDGE_USER:-propertyscope-operator}:${EDGE_PASSWORD}" "$BASE/api/data-platform/v1/artifact-retention")
    # Any answer from behind the edge except 401/403; 000 (no answer) is a failure.
    expect "valid operator credentials pass the edge" "$code" '^([235][0-9]{2}|40[45])$'
fi
code=$(status_of "$BASE/api/shared-health/ai-mode")
expect "public AI health stays readable (503 ai_disabled, or 200 when the bonus tier is on)" "$code" '^(200|503)$'
code=$(status_of "$BASE/api/data-platform/v1/sources?limit=1")
expect "ordinary feature API stays public" "$code" '^200$'

# --- Rate limiting ---------------------------------------------------------------------------
# A burst well above the edge zone (20 r/s, burst 40) from one client must see 429s. The probe is
# a missing static fragment: nginx answers it from disk (404) with try_files, which runs after
# limit_req, so the burst never reaches a feature backend or database. An edge `return` (such as
# the catch-all `location /api/` 404) runs in the rewrite phase, before limit_req, and can never
# answer 429, so it must not be used as the probe.
RATE_LIMIT_PROBE=${RATE_LIMIT_PROBE:-/fragments/rate-limit-probe}
codes=$(seq 1 150 | xargs -P 30 -I{} curl "${TLS_OPTIONS[@]}" --silent --output /dev/null --max-time 15 --write-out '%{http_code}\n' "$BASE$RATE_LIMIT_PROBE" 2>/dev/null | sort | uniq -c | tr '\n' ' ')
expect "edge rate limit (/api/ and /fragments/ zone) answers a burst on $RATE_LIMIT_PROBE with 429" "$codes" '[0-9]+ 429'
sleep 3

# --- Closed ports ----------------------------------------------------------------------------
for port in 22 2375 3389 5005 5011 5012 5013 5100 5200 5202 5300 5400 5432 5500 5600 8080; do
    if timeout 6 bash -c "exec 3<>/dev/tcp/${HOST}/${port}" 2>/dev/null; then
        result FAIL "port $port is reachable from the internet"
    else
        result PASS "port $port is closed to the internet"
    fi
done

# --- NSG (read-only Azure query) -------------------------------------------------------------
if command -v az >/dev/null 2>&1 && [[ -n ${AZURE_RESOURCE_GROUP:-} ]]; then
    allowed=$(az network nsg list --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "[].securityRules[?direction=='Inbound' && access=='Allow'].[destinationPortRange] | [] | []" \
        --output tsv 2>/dev/null | tr -d '\r' | sort -u | tr '\n' ' ')
    expect "NSG allows only 80 and 443 inbound" "${allowed% }" '^(443 80|80 443)$'
else
    result SKIP "NSG rules (needs az and AZURE_RESOURCE_GROUP)"
fi

echo "ENDPOINT_SECURITY_FAILURES=${FAILURES}" | tee -a "$REPORT"
[[ $FAILURES -eq 0 ]]
