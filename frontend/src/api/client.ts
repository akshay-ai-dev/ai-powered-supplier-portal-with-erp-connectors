import createClient from "openapi-fetch";

// Typed API client. `schema.d.ts` is generated from FastAPI's OpenAPI spec:
//   npm run gen:api   (backend must be running)
// Then swap `any` for `paths` from "./schema".
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const api = createClient<any>({
  baseUrl: import.meta.env.VITE_API_BASE_URL,
});
