import { describe, expect, it } from "vitest";

import { sanitizeChapterHtml } from "../lib/chapterHtml";

describe("sanitizeChapterHtml", () => {
  it("strips scripts and event handlers from chapter previews", () => {
    const html = `
      <html>
        <body>
          <h1 onclick="alert('x')">Chapter</h1>
          <script>alert("x")</script>
          <p>Safe text</p>
        </body>
      </html>
    `;

    const result = sanitizeChapterHtml(html);

    expect(result).toContain("<h1>Chapter</h1>");
    expect(result).toContain("<p>Safe text</p>");
    expect(result).not.toContain("script");
    expect(result).not.toContain("onclick");
  });
});
