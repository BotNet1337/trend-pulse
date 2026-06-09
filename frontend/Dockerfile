# Frontend Dockerfile — TrendPulse SPA (React + Vite, pure static).
# Multi-stage build: deps → builder (static assets) → production (nginx static).
# No SSR node server: client-side TanStack Router handles routing + 401-guard.
# Node version pinned via build-arg from development/version.env (no `latest`).
# Build-time VITE_* env vars passed as --build-arg from deploy.env (non-secret).

ARG NODE_VERSION=22.15.1
ARG NGINX_VERSION=1.27

# Stage 1: Install dependencies (cached layer)
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Stage 2: Build static assets
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
# tsc type-check → vite builds client assets into dist/
RUN npm run build

# Stage 3: Production static server (nginx — zero node runtime)
FROM nginx:${NGINX_VERSION}-alpine AS production

# Remove default nginx site config
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy built SPA static files
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx SPA config: try_files for client-side routing
COPY docker/nginx-spa.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
