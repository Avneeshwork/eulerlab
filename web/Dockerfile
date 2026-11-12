# The workbench (Next.js). It proxies /api to the Python API, so the browser
# talks to one origin; EULERLAB_API names the API container (next.config.mjs).

FROM node:22-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /web
ENV NODE_ENV=production
COPY --from=build /web/package.json /web/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY --from=build /web/.next ./.next
COPY --from=build /web/public ./public
COPY --from=build /web/next.config.mjs ./
EXPOSE 3000
# `next start -H 0.0.0.0`: the package.json script binds 127.0.0.1 for the Mac.
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
