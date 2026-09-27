# syntax=docker/dockerfile:1.7
# Generation API + queue worker. Build from the repository root:
#   docker build --platform linux/amd64 -f src/infra/docker/Dockerfile -t legolizer:local .
# The same image runs in the local compose stack and on ECS Fargate (X86_64).
FROM ubuntu:22.04

# LPub3D 2.4.9.86 is the release instructions.md uses on macOS. Its Ubuntu 22.04 package
# also ships the OSMesa LDView used for PNG renders. The 2.4.9.0 tag crashes during
# headless PDF export, and the continuous tag is mutable, so the checksum pins the file.
ARG LPUB3D_DEB_URL=https://github.com/trevorsandy/lpub3d/releases/download/continuous/LPub3D-2.4.9.86.4133_20250319-jammy-amd64.deb
ARG LPUB3D_DEB_SHA512=404723876ecea5cbf4120b2c9767ea12571396c5db6bff0ff77cb9274785b16703909de85c6af6d0543a5eded37102393da9545fcfeaf6dd2b8d60d9c4948baa

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini xauth xvfb \
 && curl -fsSL -o /tmp/lpub3d.deb "$LPUB3D_DEB_URL" \
 && echo "$LPUB3D_DEB_SHA512  /tmp/lpub3d.deb" | sha512sum -c - \
 && apt-get install -y --no-install-recommends /tmp/lpub3d.deb \
 && rm -rf /tmp/lpub3d.deb /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/
COPY src/infra/docker/lpub3d-headless /usr/local/bin/lpub3d-headless

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv python install 3.13 \
 && uv sync --locked --no-dev --no-install-project --python 3.13

# Same official-library commands as instructions.md step 2. XDG dirs stay build-only:
# at runtime LPub3D would resolve its own data dir under the read-only /opt tree.
RUN export XDG_CACHE_HOME=/opt/pyldraw/cache XDG_CONFIG_HOME=/opt/pyldraw/config \
    XDG_DATA_HOME=/opt/pyldraw/share \
 && uv run --no-sync ldraw download --yes \
 && uv run --no-sync ldraw generate --yes \
 && test -f /opt/pyldraw/cache/pyldraw3/complete/ldraw/parts.lst

COPY src/legolizer src/legolizer
COPY src/frontend/public/demo src/frontend/public/demo
RUN uv sync --locked --no-dev --python 3.13

RUN useradd --create-home --uid 10001 legolizer \
 && mkdir -p /data /home/legolizer/.config/LDView \
 && touch /home/legolizer/.config/LDView/ldviewrc \
 && chown -R legolizer /data /home/legolizer

ENV PATH=/app/.venv/bin:$PATH \
    LDRAW_LIBRARY_PATH=/opt/pyldraw/cache/pyldraw3/complete/ldraw \
    LDVIEW_BIN=/opt/lpub3d/3rdParty/ldview-4.5/bin/ldview \
    LPUB3D_BIN=/usr/local/bin/lpub3d-headless \
    LPUB3D_DISABLE_UPDATE_CHECK=1 \
    LEGOLIZER_DATA_DIR=/data \
    LEGOLIZER_HOST=0.0.0.0 \
    LEGOLIZER_PORT=8000

USER legolizer
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "legolizer.server"]
