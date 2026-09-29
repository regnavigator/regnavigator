-- 로그인 브루트포스 잠금 (2026-07-23)
-- 비번 연속 실패 카운트 + 잠금 만료 시각. 재설정(set-password) 시 리셋.
ALTER TABLE "User" ADD COLUMN "failedLoginCount" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "User" ADD COLUMN "lockedUntil" TIMESTAMP(3);
