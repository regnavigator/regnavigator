/*
 * 킬스위치 서비스 워커 (2026-09-02).
 *
 * medi-front 는 서비스 워커를 쓰지 않는다. 그런데 localhost:3000 을 공유하는 다른
 * 프로젝트(캐시 "mapexp-v2")가 등록해 둔 워커가 남아 옛 JS 청크를 캐시에서 돌려줘
 * "Cannot read properties of undefined (reading 'call')" 가 반복됐다. 브라우저는
 * 탐색 때마다 /sw.js 갱신을 확인하므로, 여기서 새 워커를 내려 주면 그 워커가
 * 기존 워커를 대체한 뒤 캐시를 비우고 스스로 등록 해제하고 열린 탭을 새로고침한다.
 * 운영에는 등록된 워커가 없어 이 파일은 요청되지 않는다(있어도 무해).
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      } catch {}
      try {
        await self.registration.unregister();
      } catch {}
      try {
        const clients = await self.clients.matchAll({ type: "window" });
        for (const c of clients) c.navigate(c.url);
      } catch {}
    })(),
  );
});
