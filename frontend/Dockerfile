FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite bakes VITE_* env vars in at build time, and this app runs client-side
# in the host browser (not inside the Docker network) — so this must be the
# browser-reachable backend address (localhost:8000, matching the backend
# service's host port mapping in docker-compose.yml), never the Docker-
# internal service name (http://backend:8000 would be unreachable from a
# browser on the host).
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

EXPOSE 5173

# `vite preview` (not a bare static-file server) — appropriate for this
# project's stated scope (a clickable demo run locally via docker-compose),
# not a hardened production deploy.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
