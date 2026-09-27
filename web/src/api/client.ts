import { initData } from "../telegram";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const DEMO_KEY = "crm-demo-role";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function demoRole(): string | null {
  try {
    return sessionStorage.getItem(DEMO_KEY);
  } catch {
    return null;
  }
}

export function setDemoRole(role: string | null): void {
  try {
    if (role) sessionStorage.setItem(DEMO_KEY, role);
    else sessionStorage.removeItem(DEMO_KEY);
  } catch {
    /* storage unavailable */
  }
}

function authorization(): string | null {
  const data = initData();
  if (data) return `tma ${data}`;
  const role = demoRole();
  return role ? `demo ${role}` : null;
}

export function hasCredentials(): boolean {
  return authorization() !== null;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const auth = authorization();
  if (auth) headers.set("Authorization", auth);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.");
  }
  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function newIdempotencyKey(): string {
  const random = crypto.getRandomValues(new Uint8Array(12));
  return Array.from(random, (b) => b.toString(16).padStart(2, "0")).join("");
}
