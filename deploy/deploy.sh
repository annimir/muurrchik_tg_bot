#!/bin/bash
set -euo pipefail

project_dir=/opt/paimon
compose_file="$project_dir/compose.prod.yml"
image_name=ghcr.io/annimir/muurrchik_tg_bot
rollback_reference="$image_name:rollback"
healthcheck_attempts="${PAIMON_HEALTHCHECK_ATTEMPTS:-24}"
started_at=

cd "$project_dir"

compose() {
    docker compose -f "$compose_file" "$@"
}

deploy_reference() {
    IMAGE_REFERENCE="$1" compose up -d --no-deps --force-recreate bot web
}

wait_for_healthy() {
    local service="$1"
    local container_id
    local status

    for ((attempt = 1; attempt <= healthcheck_attempts; attempt++)); do
        container_id=$(compose ps -q "$service")
        if [ -n "$container_id" ]; then
            status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")
            if [ "$status" = healthy ]; then
                return 0
            fi
        fi
        sleep 5
    done

    echo "Healthcheck failed for $service" >&2
    return 1
}

bot_started() {
    local container_id
    container_id=$(compose ps -q bot)
    [ -n "$container_id" ] && docker logs --since "$started_at" "$container_id" 2>&1 | grep -q 'Бот запущен'
}

deployment_healthy() {
    wait_for_healthy web && wait_for_healthy bot && bot_started
}

rollback() {
    echo "Deployment failed; restoring the previous application image" >&2
    started_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    if deploy_reference "$rollback_reference" && deployment_healthy; then
        echo "Rollback completed"
    else
        echo "Rollback failed; manual intervention is required" >&2
    fi
}

if [ "$#" -ne 1 ] || [[ ! "$1" =~ ^sha-[0-9a-f]{7,40}$ ]]; then
    echo "Usage: $0 sha-<commit>" >&2
    exit 2
fi

new_reference="$image_name:$1"
previous_image_id=$(docker inspect --format '{{.Image}}' paimon-web-1)
docker tag "$previous_image_id" "$rollback_reference"

sudo /opt/paimon/backup.sh

if [ "${PAIMON_DEPLOY_SKIP_PULL:-0}" != 1 ]; then
    docker pull "$new_reference"
fi

started_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
if ! deploy_reference "$new_reference"; then
    rollback
    exit 1
fi

if ! deployment_healthy; then
    rollback
    exit 1
fi

mkdir -p .deploy
printf '%s\n' "$new_reference" > .deploy/current-image-reference
echo "Deployment completed: $new_reference"
