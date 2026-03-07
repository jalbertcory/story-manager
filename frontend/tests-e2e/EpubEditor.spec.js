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
  await page.goto("http://localhost:5173");

  // Delete the book if it exists
  await page.request.delete("/api/books/by-title/Test Book");

  // Upload a book
  const filePath = path.resolve("test.epub");
  await dragAndDropFile(
    page,
    "#drop-zone",
    filePath,
    "test.epub",
    "application/epub+zip",
  );

  await page.getByRole("button", { name: /add book/i }).click();

  await page.reload();

  // Wait for the book to appear in the list
  await expect(page.getByText("Test Book").first()).toBeVisible({ timeout: 10000 });

  // Click the book card to edit it
  await page
    .locator(".book-card")
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

  // Click Save & Re-process
  await page.getByRole("button", { name: /save & re-process/i }).click();

  // We should be back on the book list
  await expect(page.getByText("Story Manager")).toBeVisible();

  // Verify the word count has changed
  const bookCard = page.locator(".book-card").filter({ hasText: /Test Book/i });
  await expect(bookCard.getByText(/0 words/i)).toBeVisible();

  await page.screenshot({ path: "frontend_verification.png" });
});
