FROM python:3.12 AS builder

ENV PIP_DEFAULT_TIMEOUT=200 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 

ENV RYE_HOME="/opt/rye"
ENV PATH="$RYE_HOME/shims:$PATH"
ENV UV_HTTP_TIMEOUT=1200
ENV WD_NAME=/app
WORKDIR $WD_NAME
RUN curl -sSf https://rye-up.com/get | RYE_INSTALL_OPTION="--yes" \
                                       RYE_NO_AUTO_INSTALL=1  \
                                       bash \
&& rye config --set-bool behavior.use-uv=true --set-bool autosync=false


COPY supervisor/README.md README.md
COPY supervisor/.python-version .python-version
COPY supervisor/pyproject.toml pyproject.toml
COPY supervisor/requirements.lock* requirements.lock

COPY shared shared
RUN rye add shared --path ./shared

RUN rye sync --no-lock --no-dev


ENV PATH="$WD_NAME/.venv/bin:$PATH"

FROM python:3.12-slim as runtime

ENV WD_NAME=/app
WORKDIR $WD_NAME

ENV PATH="$WD_NAME/.venv/bin:$PATH"
ENV PYTHONPATH="$PYTHONPATH:$WD_NAME/.venv/lib/python3.11/site-packages"

COPY --from=builder /opt/rye /opt/rye
COPY --from=builder $WD_NAME/.venv .venv
COPY --from=builder $WD_NAME/shared shared
COPY supervisor/src src
ENTRYPOINT ["uvicorn", "--app-dir", "src", "--host", "0.0.0.0", "main:app"]
