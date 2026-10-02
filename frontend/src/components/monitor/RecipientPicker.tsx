"use client";

/**
 * RecipientPicker — 주소록에서 수신자를 **고른다** (2026-10-02).
 *
 * 종전 수신자는 쉼표 구분 문자열이었다. 보낼 때마다 다시 타이핑하면 오타가
 * **그대로 외부로 나간다** — 규제 리포트가 엉뚱한 사람에게 가는 사고다.
 * 최근 사용 순으로 정렬해, 주소록이 커져도 쓰던 사람이 위에 온다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  createContact,
  searchContacts,
  type Contact,
} from "@/lib/client/monitorThreads";

const EMAIL_RE = /^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

export function RecipientPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (emails: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Contact[]>([]);
  const chosen = useMemo(() => new Set(selected), [selected]);

  const load = useCallback(async (term: string) => {
    try {
      setRows((await searchContacts(term)).contacts);
    } catch {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    const id = window.setTimeout(() => void load(q), 180);
    return () => window.clearTimeout(id);
  }, [q, load]);

  const toggle = (email: string) => {
    const next = new Set(chosen);
    if (next.has(email)) next.delete(email);
    else next.add(email);
    onChange([...next]);
  };

  const addNew = async () => {
    const email = q.trim();
    if (!EMAIL_RE.test(email)) {
      toast.error("이메일 형식이 아닙니다.");
      return;
    }
    try {
      await createContact({ email });
      onChange([...new Set([...selected, email])]);
      setQ("");
      await load("");
    } catch {
      toast.error("추가하지 못했습니다.");
    }
  };

  const unlisted = q.trim() && EMAIL_RE.test(q.trim())
    && !rows.some((r) => r.email === q.trim());

  return (
    <div data-testid="recipient-picker" className="flex flex-col gap-2">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="이름 · 이메일 · 소속으로 찾기"
        data-testid="recipient-search"
        className="w-full rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest px-2.5 py-1.5 text-[12.5px] outline-none focus:border-md-primary"
      />

      {selected.length ? (
        <div className="flex flex-wrap gap-1">
          {selected.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => toggle(e)}
              title="빼기"
              className="inline-flex items-center gap-1 rounded-pill bg-md-primary-container px-2 py-0.5 text-[11px] text-md-on-primary-container"
            >
              {e}
              <span className="material-symbols-outlined text-[12px]" aria-hidden>
                close
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <ul className="max-h-[200px] overflow-y-auto rounded-[8px] border border-md-outline-variant">
        {rows.length === 0 ? (
          <li className="px-2.5 py-3 text-center text-[11.5px] text-md-on-surface-variant">
            {q ? "일치하는 주소가 없습니다." : "주소록이 비어 있습니다."}
          </li>
        ) : (
          rows.map((c) => (
            <li key={c.id}>
              <label
                data-contact={c.email}
                className="flex cursor-pointer items-center gap-2 border-b border-md-outline-variant/60 px-2.5 py-1.5 text-[12px] last:border-b-0 hover:bg-md-surface-container-low"
              >
                <input
                  type="checkbox"
                  checked={chosen.has(c.email)}
                  onChange={() => toggle(c.email)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-md-on-surface">{c.display}</span>
                  <span className="block truncate text-[10.5px] text-md-on-surface-variant">
                    {c.email}
                    {c.org ? ` · ${c.org}` : ""}
                  </span>
                </span>
              </label>
            </li>
          ))
        )}
      </ul>

      {unlisted ? (
        <button
          type="button"
          data-testid="recipient-add-new"
          onClick={() => void addNew()}
          className="self-start text-[11.5px] font-medium text-md-primary underline underline-offset-2"
        >
          “{q.trim()}” 주소록에 추가하고 선택
        </button>
      ) : null}
    </div>
  );
}
