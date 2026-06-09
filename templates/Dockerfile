# Build-arg from version.env (NODE_VERSION=22.15.1) — no floating tags.
ARG NODE_VERSION=22.15.1

# Stage 1: Dependencies
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Build
FROM node:${NODE_VERSION}-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
RUN npm run build
# Copy templates.json into dist so SCHEMA_PATH=/app/dist/templates.json works
COPY templates.json ./dist/templates.json

# Stage 3: Production
FROM node:${NODE_VERSION}-alpine AS production
WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/dist ./dist

USER node
EXPOSE 3100

CMD ["node", "dist/server/main.js"]
