# syntax=docker/dockerfile:1
# Build context is the repository root (see compose.yml).
# Targets: `dev` (next dev, used by compose) and `runner` (standalone production server).

# ---------------------------------------------------------------- stage 1: deps
FROM node:22-alpine AS deps
WORKDIR /app/apps/web
# Lockfile first so `npm ci` is cached until dependencies change.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------- stage 2a: dev
FROM deps AS dev
COPY apps/web/ ./
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------- stage 2b: build
FROM deps AS build
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time,
# so the API URL must be known here, not at container start.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------- stage 3: runner
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# `output: "standalone"` puts a self-contained server.js plus the traced subset of
# node_modules in .next/standalone. public/ and .next/static are not traced and are
# copied by hand (the docs expect a CDN to serve them; we serve them ourselves).
# The tracing root is apps/web (the folder with next.config.ts), so server.js sits
# at the top of the standalone folder; nothing outside apps/web is needed.
COPY --from=build --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /app/apps/web/.next/static ./.next/static
COPY --from=build --chown=node:node /app/apps/web/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
