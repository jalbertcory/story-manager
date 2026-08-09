import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

// Helper function to simulate drag and drop
const dragAndDropFile = async (
  page,
  selector,
  filePath,
  fileName,
  fileType,
) => {
  const buffer = fs.readFileSync(filePath);
  const dataTransfer = await page.evaluateHandle(
    async ({ bufferData, localFileName, localFileType }) => {
      const dt = new DataTransfer();
      const blobData = await fetch(bufferData).then((res) => res.blob());
      const file = new File([blobData], localFileName, { type: localFileType });
      dt.items.add(file);
      return dt;
    },
    {
      bufferData: `data:application/octet-stream;base64,${buffer.toString(
        "base64",
      )}`,
      localFileName: fileName,
      localFileType: fileType,
    },
  );

  await page.dispatchEvent(selector, "drop", { dataTransfer });
};

test("EpubEditor interactions", async ({ page }) => {
  await page.goto("/");

  // Delete the book if it exists
  await page.request.delete("/api/books/by-title/Test Book");

  // Open the guided import workflow.
  await page.getByRole("button", { name: "Add to library" }).click();

  // Upload a book
  const filePath = path.resolve("test.epub");
  await dragAndDropFile(
    page,
    "#drop-zone",
    filePath,
    "test.epub",
    "application/epub+zip",
  );

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/api/imports/preview") &&
        response.status() === 200,
    ),
    page.getByRole("button", { name: "Inspect selection" }).click(),
  ]);

  await expect(
    page.getByRole("heading", { name: "Review before importing" }),
  ).toBeVisible();
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/api/books/upload_epubs") &&
        response.status() === 200,
    ),
    page.getByRole("button", { name: /import 1 ready/i }).click(),
  ]);

  await page.getByRole("link", { name: "Library", exact: true }).click();

  // Narrow the library down so "Test Book" is in the first page (list renders 30 items at a time).
  await page.getByPlaceholder("Search by title, author, series, or tag").fill("Test Book");

  // Standalone books now live behind their own tab in the library.
  await page.getByRole("tab", { name: /standalone/i }).click();
  await expect(page.getByText("Test Book").first()).toBeVisible({ timeout: 10000 });

  // Click the standalone library row to edit it
  await page
    .locator(".book-row")
    .filter({ hasText: /Test Book/i })
    .click();

  // The book settings panel should now be visible
  await expect(page.getByRole("heading", { name: "Test Book" })).toBeVisible();

  // Expand the chapter list
  await page.getByRole("button", { name: /expand/i }).click();

  // Check if the chapter is listed
  await expect(page.getByText("Introduction")).toBeVisible();

  // Uncheck the chapter to remove it
  await page
    .getByRole("listitem")
    .filter({ hasText: "Introduction" })
    .getByRole("checkbox")
    .uncheck();

  // Add a content selector to remove
  await page.getByPlaceholder("Add CSS selector, e.g. div.note").fill("p");
  await page.getByRole("button", { name: "Add" }).click();

  // Save edits and queue the generated EPUB rebuild.
  const [processingResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        /\/api\/books\/\d+\/process$/.test(new URL(response.url()).pathname) &&
        response.status() === 200,
    ),
    page
      .getByRole("button", { name: /queue epub rebuild from saved edits/i })
      .click(),
  ]);
  const processedBook = await processingResponse.json();

  await expect(page.getByRole("status")).toContainText(
    "EPUB cleaning job queued",
  );

  // The action returns when durable work is queued. Wait for every cleaning
  // job for this book to finish before checking its regenerated word count.
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `/api/processing/jobs?job_type=clean_book&book_id=${processedBook.id}&limit=20`,
        );
        if (!response.ok()) return "request-failed";
        const jobs = await response.json();
        if (!jobs.length) return "missing";
        if (jobs.some((job) => ["queued", "running"].includes(job.status))) {
          return "active";
        }
        if (jobs.some((job) => job.status === "error")) return "error";
        return jobs.every((job) => job.status === "completed")
          ? "completed"
          : "terminal";
      },
      { timeout: 30000 },
    )
    .toBe("completed");

  // Go back to the book list and reload the catalog after processing.
  await page.getByRole("button", { name: /back/i }).click();
  await page.reload();
  await expect(page.getByText("Story Manager")).toBeVisible();
  await page.getByPlaceholder("Search by title, author, series, or tag").fill("Test Book");
  await page.getByRole("tab", { name: /standalone/i }).click();

  // Verify the word count has changed
  const bookRow = page.locator(".book-row").filter({ hasText: /Test Book/i });
  await expect(bookRow.getByText(/0 words/i)).toBeVisible();

  await page.screenshot({ path: "frontend_verification.png" });
});
