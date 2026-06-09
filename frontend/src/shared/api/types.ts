import type { paths } from './gen.types';

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete';

type Operation<P extends keyof paths, M extends Method> =
    paths[P] extends { [K in M]?: infer Op } ? Op : never;

type ResponsesOf<P extends keyof paths, M extends Method> =
    Operation<P, M> extends { responses: infer R } ? R : never;

type JsonResponseUnion<R> = {
    [Status in keyof R]: R[Status] extends {
        content: { 'application/json': infer Res };
    }
    ? Res
    : never;
}[keyof R];

export type OpenApiResponse<P extends keyof paths, M extends Method> =
    ResponsesOf<P, M> extends infer R ? JsonResponseUnion<R> : never;

export type OpenApiBody<P extends keyof paths, M extends Method> =
    Operation<P, M> extends {
        requestBody: {
            content: { 'application/json': infer Body };
        };
    }
    ? Body
    : never;

export type OpenApiPathParams<P extends keyof paths, M extends Method> =
    Operation<P, M> extends {
        parameters: { path: infer PathParams };
    }
    ? PathParams
    : never;

export type OpenApiQueryParams<P extends keyof paths, M extends Method> =
    Operation<P, M> extends {
        parameters: { query?: infer QueryParams };
    }
    ? QueryParams
    : never;

/**
 * Generic paginated envelope shared by every list endpoint. The meta shape
 * is pulled straight from the OpenAPI-generated `ListWorkspacesResponseDto`
 * so it stays in sync with the backend's `PaginatedResponse<T>` contract —
 * if the backend ever changes the meta shape, regenerating types will
 * surface the diff at every list-feature site.
 */
type ListResponse = paths['/workspaces']['get'] extends {
    responses: { 200: { content: { 'application/json': infer R } } };
}
    ? R
    : never;

export type PaginatedResponseMeta = ListResponse extends { meta: infer M } ? M : never;

export interface PaginatedResponse<T> {
    data: T[];
    meta: PaginatedResponseMeta;
}
