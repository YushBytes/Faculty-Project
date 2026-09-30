# ACADLYTICS web (Next.js). The browser talks only to this server; /api/v1/* and the
# session routes are forwarded to the API container at ACADLYTICS_API_URL.
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --fetch-retries=6 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web/package.json /web/package-lock.json ./
COPY --from=build /web/node_modules ./node_modules
COPY --from=build /web/.next ./.next
COPY --from=build /web/public ./public
COPY --from=build /web/next.config.ts ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
