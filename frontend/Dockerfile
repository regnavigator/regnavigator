# medi-front — Next.js 15 standalone build
# 핸드오프: medi-back과 같은 GCP VM에서 self-hosted runner + docker compose로 빌드

# ─── deps: node_modules 캐시 레이어
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json prisma ./
RUN npm ci

# ─── builder: prisma generate + next build (standalone)
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx prisma generate
# NEXT_PUBLIC_* 변수는 build 시점에 client bundle에 inline되어야 함 — runtime env 무용.
# 모든 NEXT_PUBLIC_* 변수를 ARG로 받아 ENV로 전달 후 build.
ARG NEXT_PUBLIC_DEPLOYMENT_URL
ARG NEXT_PUBLIC_ASSISTANT_ID
ARG NEXT_PUBLIC_ASSISTANT_ID_DEEP
ARG NEXT_PUBLIC_LANGSMITH_KEY
ARG NEXT_PUBLIC_DUMMY_MODE
ARG NEXT_PUBLIC_AUTH_BYPASS
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_SUPPORT_EMAIL
ARG NEXT_PUBLIC_MAIL_FROM
ARG NEXT_PUBLIC_ROOT_ADMIN_EMAIL
ENV NEXT_PUBLIC_DEPLOYMENT_URL=${NEXT_PUBLIC_DEPLOYMENT_URL} \
    NEXT_PUBLIC_ASSISTANT_ID=${NEXT_PUBLIC_ASSISTANT_ID} \
    NEXT_PUBLIC_ASSISTANT_ID_DEEP=${NEXT_PUBLIC_ASSISTANT_ID_DEEP} \
    NEXT_PUBLIC_LANGSMITH_KEY=${NEXT_PUBLIC_LANGSMITH_KEY} \
    NEXT_PUBLIC_DUMMY_MODE=${NEXT_PUBLIC_DUMMY_MODE} \
    NEXT_PUBLIC_AUTH_BYPASS=${NEXT_PUBLIC_AUTH_BYPASS} \
    NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL} \
    NEXT_PUBLIC_SUPPORT_EMAIL=${NEXT_PUBLIC_SUPPORT_EMAIL} \
    NEXT_PUBLIC_MAIL_FROM=${NEXT_PUBLIC_MAIL_FROM} \
    NEXT_PUBLIC_ROOT_ADMIN_EMAIL=${NEXT_PUBLIC_ROOT_ADMIN_EMAIL}
RUN npm run build

# ─── migrator: `prisma migrate deploy` 전용 one-shot 이미지.
# standalone 러너(runner)엔 prisma CLI가 없어(devDep·trace 제외) 마이그레이션을
# 못 돌린다. builder는 전체 소스(/app/prisma/schema.prisma) + node_modules(prisma
# CLI 포함, deps의 npm ci가 devDep까지 설치)를 이미 갖고 있어 그대로 재사용.
# compose의 medi-front-migrate 서비스가 이 타깃으로 떠서 배포마다 1회 실행 후 종료.
FROM builder AS migrator
WORKDIR /app
CMD ["npx", "prisma", "migrate", "deploy"]

# ─── runner: 최소 production 이미지
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/prisma ./prisma
COPY --from=builder --chown=nextjs:nodejs /app/node_modules/.prisma ./node_modules/.prisma
# SQLite DB volume mountpoint 미리 생성 + nextjs(1001) 소유로 — fresh 볼륨이
# root로 만들어져 쓰기 거부되는 사고 차단. Postgres 운영 전환 시엔 무해(미사용).
RUN mkdir -p /app/prisma/data && chown -R nextjs:nodejs /app/prisma
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
