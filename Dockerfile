# Imagem do monitoramento de túneis: coletor + painel no mesmo container, como no Render.
# Os dados (banco SQLite e JSONs brutos do feed) ficam em /app/data, que é o ponto de montagem
# do volume: é o que faz o histórico sobreviver a `docker compose down` e a novos builds.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

# tzdata: o projeto usa o fuso de Brasília para tipo de dia e slots de 15 min
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# Dependências antes do código: mudar o código não invalida a camada do pip
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# /app/data precisa existir na imagem com o dono certo: o Docker copia essa permissão para
# o volume na primeira criação (senão o volume nasce como root e o coletor não consegue gravar)
RUN useradd --create-home --uid 1000 tuneis \
 && mkdir -p /app/data \
 && chown -R tuneis:tuneis /app/data
USER tuneis

ENV TUNEIS_DB=/app/data/tuneis.db \
    TUNEIS_FEEDS=/app/data/feeds

EXPOSE 8501

# Sem curl na imagem slim: a checagem usa a própria stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

# Mesmo script do Render: coletor em segundo plano (reinicia se cair) + painel em primeiro plano
CMD ["bash", "render-start.sh"]
