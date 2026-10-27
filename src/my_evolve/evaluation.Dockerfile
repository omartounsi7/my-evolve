# The image in which DockerSandbox runs the programs written by the LLM (D71).
# Only the program's worker runs here; the evaluation file stays on the host (D8).
# The my_evolve package is mounted at run time, read-only.
FROM python:3.12-slim

# The packages programs may import: the problem file's list, possibly empty. This is
# the only moment with network access: the containers themselves have none.
COPY requirements.txt /tmp/requirements.txt
RUN if [ -s /tmp/requirements.txt ]; then \
        pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
            --requirement /tmp/requirements.txt; \
    fi \
    && rm /tmp/requirements.txt

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

# "nobody": a user without any rights.
USER 65534:65534
WORKDIR /tmp
