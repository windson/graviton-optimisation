# Build stage: install dependencies, bundle the server and browser code, run the tests.
FROM public.ecr.aws/docker/library/node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && npm test && npm prune --omit=dev

# Runtime stage: production dependencies and the built bundles only.
FROM public.ecr.aws/docker/library/node:24-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist/server.mjs ./dist/server.mjs
COPY --from=build /app/dist/public ./dist/public
COPY package.json ./

USER node
EXPOSE 3000
CMD ["node", "dist/server.mjs"]
