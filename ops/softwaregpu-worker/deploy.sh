#!/usr/bin/env bash
# Deploy only the separately scoped ARE worker; never prune a shared VPS.
set -Eeuo pipefail
umask 077

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${HERE}/../.." && pwd)"
PROJECT="are-softwaregpu"
SERVICE="are-softwaregpu-worker"
CONFIG="${HERE}/compose.yaml"
PRIVATE_DIR="/opt/are-softwaregpu/private"
PASSWORD_PATH="${PRIVATE_DIR}/gradio-password"

if [[ "${EUID}" -ne 0 ]]; then
    echo "ARE_WORKER_ROOT_REQUIRED: use the authorized VPS administrator" >&2
    exit 2
fi
for command_name in docker git openssl; do
    command -v "${command_name}" >/dev/null ||
      { echo "ARE_WORKER_DEPENDENCY_MISSING: ${command_name}" >&2; exit 2; }
done
docker compose version >/dev/null
expected="${ARE_EXPECTED_SOURCE_SHA:?Pass exact reviewed 40-character commit in ARE_EXPECTED_SOURCE_SHA}"
if [[ ! "${expected}" =~ ^[a-f0-9]{40}$ ]]; then
    echo "ARE_WORKER_SHA_INVALID" >&2
    exit 2
fi
actual="$(git -C "${ROOT}" rev-parse HEAD)"
if [[ "${actual}" != "${expected}" ]]; then
    echo "ARE_WORKER_SHA_MISMATCH: refusing unverified checkout" >&2
    exit 3
fi
if ! git -C "${ROOT}" diff --quiet || ! git -C "${ROOT}" diff --cached --quiet; then
    echo "ARE_WORKER_DIRTY_CHECKOUT" >&2
    exit 3
fi
export COMPOSE_PROJECT_NAME="${PROJECT}"
export ARE_GRADIO_USER="${ARE_GRADIO_USER:-owner}"
if [[ ! "${ARE_GRADIO_USER}" =~ ^[a-zA-Z0-9_-]{1,40}$ ]]; then
    echo "ARE_GRADIO_USER_INVALID" >&2
    exit 2
fi

# Only the credential survives service replacements. Not a Docker volume.
install -d -m 0700 /opt/are-softwaregpu
install -d -m 0700 "${PRIVATE_DIR}"
if [[ -L "${PASSWORD_PATH}" ]]; then
    echo "ARE_WORKER_PASSWORD_SYMLINK_DENIED" >&2
    exit 3
fi
if [[ ! -e "${PASSWORD_PATH}" ]]; then
    temp="$(mktemp "${PRIVATE_DIR}/.password.XXXXXXXX")"
    trap 'rm -f -- "${temp:-}"' EXIT
    openssl rand -hex 32 >"${temp}"
    # Directory is root-only on the host. The non-root container reads
    # this single read-only Compose secret through /run/secrets.
    chmod 0444 "${temp}"
    mv -n -- "${temp}" "${PASSWORD_PATH}"
    trap - EXIT
fi
if [[ ! -s "${PASSWORD_PATH}" ]]; then
    echo "ARE_WORKER_PASSWORD_UNAVAILABLE" >&2
    exit 3
fi
export ARE_GRADIO_PASSWORD_PATH="${PASSWORD_PATH}"
export ARE_EXPECTED_SOURCE_SHA="${expected}"

docker compose -p "${PROJECT}" -f "${CONFIG}" config --quiet
docker compose -p "${PROJECT}" -f "${CONFIG}" up --build -d --remove-orphans --wait --wait-timeout 120

# Cleanup after health/readback only. Never issue prune (global or scoped).
# Docker Compose itself has already removed replaced worker containers.
while IFS= read -r container_id; do
    [[ -n "${container_id}" ]] || continue
    docker container rm "${container_id}" >/dev/null
done < <(docker ps -aq --filter "label=com.docker.compose.project=are-softwaregpu" \
                       --filter "label=org.ouroboros.service=are-softwaregpu-worker" \
                       --filter "status=exited")

# Only dangling, independently labelled ARE build images without any user.
# Docker images that are still in use by *any* container are untouched.
while IFS= read -r image_id; do
    [[ -n "${image_id}" ]] || continue
    if docker ps -aq --filter "ancestor=${image_id}" | grep -q .; then
        continue
    fi
    docker image rm "${image_id}" >/dev/null
done < <(docker image ls -q --no-trunc --filter "dangling=true" \
                      --filter "label=org.ouroboros.service=are-softwaregpu-worker" | sort -u)

# Our current Compose stack defines zero volumes. Only unused, explicitly
# disposable ARE volumes carrying *both* owner and lifecycle labels qualify.
while IFS= read -r volume_name; do
    [[ -n "${volume_name}" ]] || continue
    if docker ps -aq --filter "volume=${volume_name}" | grep -q .; then
        continue
    fi
    docker volume rm "${volume_name}" >/dev/null
done < <(docker volume ls -q --filter "label=com.docker.compose.project=are-softwaregpu" \
                       --filter "label=org.ouroboros.lifecycle=disposable")

echo "ARE_WORKER_DEPLOYED: sha=${actual}; cpus<=3; host=127.0.0.1:17860; old disposable resources removed"
echo "HTTPS and DNS must be verified separately for gpu.arelorian.de; no host-wide Docker cleanup performed"
