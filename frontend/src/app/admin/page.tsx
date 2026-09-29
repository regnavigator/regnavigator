import { redirect } from "next/navigation";

/** /admin 진입점 — 종전 404. 첫 화면은 통계로. */
export default function AdminIndexPage() {
  redirect("/admin/stats");
}
