FROM python:3.12-slim

LABEL org.opencontainers.image.title="CLOVER" \
      org.opencontainers.image.description="Reproducible, auditable and self-checking course-outcome attainment assessment" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/SHELLY000/Clover"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY clover ./clover
COPY blueprints ./blueprints
COPY examples ./examples
RUN pip install --no-cache-dir .

WORKDIR /work
ENTRYPOINT ["clover"]
CMD ["--help"]
