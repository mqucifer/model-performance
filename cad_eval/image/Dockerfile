# The CAD-code evaluation's sandbox image: CadQuery and the checker's mesh library,
# nothing else (mqucifer/model-performance#3). Generated code runs only in a
# container from this image, under crew's sandbox (`cad_eval/container.py`), never
# on the host. Built on the Mac by `cad_eval/image/build.sh`.
# The `-osmesa` tag (mqucifer/model-performance#29) adds only libosmesa6, so VTK can
# render offscreen for the `view` tool: `build.sh model-performance/cadquery:2.8.0-osmesa
# libosmesa6`. The CadQuery path is the same in both tags.
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

ARG EXTRA_PACKAGES=""
# OCCT's wheel links against these X and GL libraries even with no display.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 \
       $EXTRA_PACKAGES \
    && rm -rf /var/lib/apt/lists/*

# Every package pinned: the image is rebuilt the same from this file.
COPY requirements.txt /opt/cad-eval/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /opt/cad-eval/requirements.txt \
    && python -c "import cadquery, trimesh; print(cadquery.__version__, trimesh.__version__)"

# crew's sandbox runs as the invoking user on a read-only filesystem: nothing here
# may need to write outside /work and /tmp.
ENV PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp NUMBA_CACHE_DIR=/tmp
