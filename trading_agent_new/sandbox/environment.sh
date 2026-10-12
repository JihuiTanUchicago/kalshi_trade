# Source from the Polygon workspace root to use its isolated Lima/Docker setup.
if [ ! -f "$PWD/sandbox/Dockerfile" ] || [ ! -d "$PWD/.runtime/docker-cli" ]; then
    printf '%s\n' 'Run this from the Polygon workspace root after runtime setup.' >&2
    return 1
fi
export PATH="$PWD/.runtime/docker-cli:$PATH"
export LIMA_HOME="$PWD/.runtime/lima"
export DOCKER_CONFIG="$PWD/.runtime/docker-config"
export DOCKER_HOST="unix://$PWD/.runtime/lima/quant-docker/sock/docker.sock"
export TMPDIR="$PWD/.runtime/strategy-tmp"
