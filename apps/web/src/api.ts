let csrfToken = '';
export const setCsrfToken = (token: string) => { csrfToken = token; };
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
interface RequestOptions extends Omit<RequestInit, 'body'> { body?: unknown }

async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  const { body, ...rest } = options;
  const method = options.method ?? 'GET';
  const headers = new Headers(options.headers);
  headers.set('X-Requested-With', 'SJLERP');
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && path !== '/auth/login') {
    headers.set('X-CSRF-Token', csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...rest, method, headers, credentials: 'same-origin',
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查网络或服务运行状态后重试。');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    if (response.status === 401 && path !== '/auth/login') {
      csrfToken = '';
      window.dispatchEvent(new Event('sjlerp:unauthorized'));
    }
    throw new ApiError(response.status, data?.error?.code ?? 'REQUEST_FAILED',
      data?.error?.message ?? (response.status === 403 ? '当前账号没有此操作权限。' : `请求失败（${response.status}），请稍后重试。`));
  }
  return response;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await request(path, options);
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
export async function download(path: string, filename: string): Promise<void> {
  const response = await request(path);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试。';
