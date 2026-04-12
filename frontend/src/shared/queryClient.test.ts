import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/shared/api";
import { queryClient } from "@/shared/queryClient";

describe("queryClient", () => {
    beforeEach(() => {
        queryClient.clear();
    });

    it("clears cached data when a 401 reaches the global query error handler", () => {
        queryClient.setQueryData(["admin", "summary"], { active_courses: 2 });

        queryClient.getQueryCache().config.onError?.(
            new ApiError(401, "unauthorized", "invalid_token"),
            {} as never,
        );

        expect(queryClient.getQueryData(["admin", "summary"])).toBeUndefined();
    });
});
