import { describe, it, expect } from "vitest";
import { Marked } from "marked";

import { SAFE_MARKDOWN_RENDERER } from "./safeMarkdown";

// Mirror the global CaseContentRenderer config (gfm + the shared security renderer).
const md = new Marked({ gfm: true, breaks: false });
md.use({ renderer: SAFE_MARKDOWN_RENDERER });
const render = (markdown: string): string => md.parse(markdown) as string;

describe("SAFE_MARKDOWN_RENDERER — XSS hardening for dangerouslySetInnerHTML sinks", () => {
    it("drops raw <script> blocks", () => {
        const out = render("Intro\n\n<script>alert(document.cookie)</script>\n\nfin");
        expect(out).not.toContain("<script");
        expect(out).not.toContain("alert(document.cookie)");
    });

    it("drops inline event-handler HTML such as <img onerror>", () => {
        const out = render('texto <img src=x onerror="alert(1)"> texto').toLowerCase();
        expect(out).not.toContain("onerror");
        expect(out).not.toContain("<img src=x");
    });

    it("neutralizes javascript: markdown links (renders inert text)", () => {
        const out = render("[haz clic](javascript:alert(1))");
        expect(out).not.toContain("javascript:");
        expect(out).toContain("haz clic");
    });

    it("neutralizes javascript:/data: markdown image sources", () => {
        expect(render("![x](javascript:alert(1))")).not.toContain("javascript:");
        expect(render("![x](data:text/html;base64,PHNjcmlwdD4=)")).not.toContain("data:");
    });

    it("preserves safe markdown: bold, headings, and http(s) links", () => {
        const out = render("# Título\n\n**negrita** y [sitio](https://example.com).");
        expect(out).toContain("<strong>negrita</strong>");
        expect(out).toContain('href="https://example.com"');
        expect(out).toContain('rel="noopener noreferrer"');
        expect(out).toContain("Título");
    });

    it("strips HTML smuggled inside a link label (label-bypass of the html override)", () => {
        const out = render("[<img src=x onerror=alert(1)>](https://example.com)");
        expect(out).not.toMatch(/<img/i);
        expect(out).not.toContain("onerror=alert");
    });

    it("strips a tag-breakout + <script> inside a link label", () => {
        const out = render("[</a><script>alert(1)</script>](https://example.com)");
        expect(out).not.toContain("<script");
    });

    it("preserves inline markup inside a link label (no raw-source regression)", () => {
        const out = render("[**bold** label](https://example.com)");
        expect(out).toContain("<strong>bold</strong>");
        expect(out).toContain('href="https://example.com"');
    });

    it("neutralizes mixed-case and entity-encoded javascript: hrefs", () => {
        expect(render("[x](JavaScript:alert(1))")).not.toMatch(/<a\s/i);
        expect(render("[x](&#106;avascript:alert(1))")).not.toMatch(/<a\s/i);
    });
});
