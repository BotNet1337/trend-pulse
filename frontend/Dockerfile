# Stage 1: Dependencies
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
# tsc type-check, then vite builds client assets into dist/client
RUN npx tsc -b && npx vite build --outDir dist/client

# Stage 3: Production
FROM node:22-alpine AS production
WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/src ./src
COPY --from=builder /app/server ./server
COPY --from=builder /app/tsconfig.json ./
COPY --from=builder /app/tsconfig.node.json ./
COPY --from=builder /app/tsconfig.app.json ./
COPY package.json package-lock.json ./

# tsx and cross-env are devDependencies but required at runtime for SSR server
RUN npm ci && npm cache clean --force

ENV NODE_ENV=production
ENV PORT=4000

USER node
EXPOSE 4000

CMD ["npm", "run", "start"]
