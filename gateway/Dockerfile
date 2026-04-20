# Stage 1: compile TypeScript → dist/
FROM node:20 AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: production runtime — only compiled JS + prod deps
# node:20 (not slim) because better-sqlite3 is a native module that must
# be compiled from source during npm ci, which requires python3 + make + g++.
FROM node:20 AS runtime
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/dist ./dist
EXPOSE 3000
CMD ["node", "dist/server.js"]
