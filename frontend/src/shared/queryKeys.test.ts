import { describe, expect, it } from "vitest";

import { queryKeys } from "./queryKeys";

describe("queryKeys.teacher", () => {
    it("returns the teacher root key", () => {
        expect(queryKeys.teacher.all()).toEqual(["teacher"]);
    });

    it("returns the teacher courses key", () => {
        expect(queryKeys.teacher.courses()).toEqual(["teacher", "courses"]);
    });

    it("returns the teacher cases key", () => {
        expect(queryKeys.teacher.cases()).toEqual(["teacher", "cases"]);
    });

    it("returns the teacher case key", () => {
        expect(queryKeys.teacher.case("abc")).toEqual(["teacher", "case", "abc"]);
    });
});
