# Frontend Dockerfile — TrendPulse SPA (React + Vite SSR).
# Multi-stage build: deps → builder (static assets) → production (SSR server).
# Node version pinned via build-arg from development/version.env (no `latest`).
# Build-time VITE_* env vars passed as --build-arg from deploy.env (non-secret).

ARG NODE_VERSION=22.15.1

# Stage 1: Install dependencies (cached layer)
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Stage 2: Build static assets + type-check
FROM node:${NODE_VERSION}-alpine AS builder
ARG VITE_BRAND_NAME=TrendPulse
ARG VITE_HELP_URL=https://trendpulse.app/docs
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
# Build-time brand injection (non-secret VITE_* vars baked into the bundle)
ENV VITE_BRAND_NAME=${VITE_BRAND_NAME}
ENV VITE_HELP_URL=${VITE_HELP_URL}
# tsc type-check → vite builds client assets into dist/client
RUN npm run build

# Stage 3: Production SSR server (minimal runtime)
FROM node:${NODE_VERSION}-alpine AS production
WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/src ./src
COPY --from=builder /app/server ./server
COPY --from=builder /app/tsconfig.json ./
COPY --from=builder /app/tsconfig.node.json ./
COPY --from=builder /app/tsconfig.app.json ./
COPY package.json package-lock.json ./

# tsx and cross-env are devDependencies but required at runtime for SSR server
RUN npm ci --ignore-scripts && npm cache clean --force

ENV NODE_ENV=production
# SSR server port (nginx proxies to this internally — not published to host)
ENV PORT=4000

USER node
EXPOSE 4000

CMD ["npm", "run", "start"]
