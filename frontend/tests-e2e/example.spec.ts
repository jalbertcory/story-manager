import { test, expect } from "@playwright/test";

test("homepage has expected title", async ({ page }) => {
  await page.goto("/");

  // Expect a title "to contain" a substring.
  await expect(page).toHaveTitle(/Story Manager/);

  // Expect an h1 to contain the text "Story Manager".
  const locator = page.locator("h1");
  await expect(locator).toContainText("Story Manager");
});
