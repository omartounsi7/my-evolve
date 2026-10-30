# The image in which the Docker sandbox runs the programs written by the LLM.
# The my_evolve package is mounted at run time, read-only; the evaluation file stays on
# the host. Building is the only moment with network access: the containers have none.
FROM python:3.12-slim

# The packages programs may import: the problem file's list, possibly empty.
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
