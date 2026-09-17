# syntax=docker/dockerfile:1
# Build context is the repository root (see compose.yml).
# Targets: `dev` (Vite dev server, used by compose) and `prod` (static build behind nginx).

# ---------------------------------------------------------------- stage 1: deps
FROM node:22-alpine AS deps
WORKDIR /app/apps/web
# Lockfile first so `npm ci` is cached until dependencies change.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------- stage 2a: dev
FROM deps AS dev
COPY apps/web/ ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# ---------------------------------------------------------------- stage 2b: build
FROM deps AS build
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------- stage 3: prod
FROM nginx:alpine AS prod
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
