# Frontend Dockerfile — TrendPulse SSR server (React + Vite + Fastify/Node).
# Multi-stage build: deps → builder (tsc + vite → dist/client) → production (node-SSR).
# prod stage runs the Fastify SSR server on :4000 (not nginx-static).
# Node version pinned via build-arg from development/version.env (no `latest`).
# Build-time VITE_* env vars passed as --build-arg from deploy.env (non-secret).
# Runtime secrets (API_URL, COOKIE_SECRET) injected via Docker env at runtime.

ARG NODE_VERSION=22.15.1

# Stage 1: Install dependencies (cached layer)
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# --ignore-scripts is safe here — no postinstall scripts needed
RUN npm ci --ignore-scripts

# Stage 2: Build static client assets + type-check
FROM node:${NODE_VERSION}-alpine AS builder
ARG VITE_BRAND_NAME=TrendPulse
ARG VITE_HELP_URL=https://foresignal.biz/docs
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
# Build-time brand injection (non-secret VITE_* vars baked into the bundle)
ENV VITE_BRAND_NAME=${VITE_BRAND_NAME}
ENV VITE_HELP_URL=${VITE_HELP_URL}
# tsc type-check (tsconfig references: app + node) → vite build → dist/client/
# The SSR server (server/) is executed via tsx at runtime — NOT bundled here.
RUN npm run build

# Stage 3: Production SSR server (node runtime, not nginx)
FROM node:${NODE_VERSION}-alpine AS production
WORKDIR /app

# Copy built client assets (served as static files by fastify-static in prod)
COPY --from=builder /app/dist ./dist

# Copy server source (executed by tsx at runtime)
COPY --from=builder /app/server ./server

# Copy source files needed by the server at runtime (SSR render imports src/app/*)
COPY --from=builder /app/src ./src

# Copy node_modules (tsx, fastify, axios, etc. are runtime deps — not --omit=dev)
COPY --from=deps /app/node_modules ./node_modules

# Copy manifests + tsconfigs (tsx needs tsconfig.app.json for path aliases)
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/tsconfig.json ./tsconfig.json
COPY --from=builder /app/tsconfig.app.json ./tsconfig.app.json
COPY --from=builder /app/tsconfig.node.json ./tsconfig.node.json

ENV NODE_ENV=production

# Runtime env — MUST be provided via Docker/compose environment:
#   API_URL        — internal backend URL (e.g. http://api:8000)
#   COOKIE_SECRET  — ≥16 char secret for @fastify/cookie signature
# These are validated by server/config.ts Zod schema on startup (fail-fast).
# Do NOT hardcode them here.

EXPOSE 4000

# tsx resolves TypeScript path aliases from tsconfig.app.json
CMD ["npm", "run", "start"]
