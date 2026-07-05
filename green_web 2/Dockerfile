FROM node:22-slim AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY index.html ./
COPY public ./public
COPY src ./src
COPY vite.config.js ./
RUN npm run build

FROM node:22-slim AS dependencies

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev

FROM node:22-slim

ENV NODE_ENV=production
WORKDIR /app

COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package*.json ./
COPY public ./public
COPY src ./src

EXPOSE 3000

CMD ["npm", "start"]
