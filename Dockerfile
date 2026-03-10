FROM oven/bun:1.3 AS base
WORKDIR /app

COPY package.json bun.lock* ./
RUN bun install --frozen-lockfile --production

COPY src/ src/

# SQLite data lives on the persistent volume
ENV COWORK_MAIL_DB=/data/cowork-mail.db
ENV COWORK_MAIL_PORT=3141

EXPOSE 3141

CMD ["bun", "run", "src/index.ts"]
