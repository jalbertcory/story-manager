import { test, expect } from "@playwright/test";
import path from "path";

test("EpubEditor interactions", async ({ page }) => {
  await page.goto("http://localhost:5173");

  // Upload a book
  const filePath = path.resolve("test.epub");
  await page.setInputFiles('input[type="file"]', filePath);
  await page.getByRole("button", { name: /upload/i }).click();

  // Wait for the book to appear in the list
  await expect(page.getByText("Test Book")).toBeVisible({ timeout: 10000 });

  // Click the "Edit" button for the new book
  await page
    .getByRole("row", { name: /Test Book/i })
    .getByRole("button", { name: /edit/i })
    .click();

  // The editor should now be visible
  await expect(page.getByText("Editing: Test Book")).toBeVisible();

  // Check if the chapter is listed
  await expect(page.getByText("Introduction")).toBeVisible();

  // Uncheck the chapter to remove it
  await page.getByLabel("Introduction").uncheck();

  // Add a div selector to remove
  await page.getByPlaceholder("e.g., note, author-note").fill("p");

  // Click the save button
  await page.getByRole("button", { name: /save/i }).click();

  // We should be back on the book list
  await expect(page.getByText("Story Manager")).toBeVisible();

  // Verify the word count has changed
  await expect(
    page.getByRole("row", { name: /Test Book/i }).getByText("0"),
  ).toBeVisible();

  await page.screenshot({ path: "frontend_verification.png" });
});
