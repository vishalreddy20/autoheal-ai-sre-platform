FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_AUTOHEAL_ENGINE_URL=http://localhost:8003
ARG VITE_SSE_URL=http://localhost:8000/stream/events
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_AUTOHEAL_ENGINE_URL=$VITE_AUTOHEAL_ENGINE_URL
ENV VITE_SSE_URL=$VITE_SSE_URL
RUN npm run build

FROM nginx:alpine AS final
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:80/health || exit 1
CMD ["nginx", "-g", "daemon off;"]
