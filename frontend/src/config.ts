/** Single source of truth for where the backend lives.
 *
 *  This used to be copy-pasted into five modules, so changing it meant five
 *  edits and one of them was always missed.
 *
 *  Override without touching source by creating `frontend/.env.local`:
 *      VITE_BACKEND_URL=http://localhost:8000
 *  (Vite only exposes vars prefixed with VITE_, and .env* is git-ignored.)
 */

const DEFAULT_BACKEND_URL = "https://anniversary-mortgage-truck-top.trycloudflare.com";

/** No trailing slash — every caller appends "/api/...". */
export const BACKEND_URL = (
  import.meta.env.VITE_BACKEND_URL ?? DEFAULT_BACKEND_URL
).replace(/\/+$/, "");
