import { expect, test } from "@playwright/test";

test("groups pages under canonical destinations and preserves history", async ({
  page,
}) => {
  await page.goto("/activity");

  const primary = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(primary.getByRole("link")).toHaveCount(3);
  await expect(primary.getByRole("link", { name: "Library" })).toBeVisible();
  await expect(primary.getByRole("link", { name: /Activity/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(primary.getByRole("link", { name: "Settings" })).toBeVisible();

  await page.getByRole("link", { name: "Processing jobs" }).click();
  await expect(page).toHaveURL(/\/activity\/processing$/);
  await expect(
    page.getByRole("heading", { name: "Processing control" }),
  ).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/activity$/);
  await expect(
    page.getByRole("heading", { name: "Needs attention" }),
  ).toBeVisible();

  await page.goto("/utilities?section=reader-access");
  await expect(page).toHaveURL(
    /\/settings\/library-tools\?section=reader-access$/,
  );
  await expect(
    page.getByRole("tab", { name: "Reader Access" }),
  ).toHaveAttribute("aria-selected", "true");

  await page.getByRole("tab", { name: "Storage" }).click();
  await expect(page).toHaveURL(/\?section=storage$/);
  await page.goBack();
  await expect(
    page.getByRole("tab", { name: "Reader Access" }),
  ).toHaveAttribute("aria-selected", "true");
});

test("keeps primary navigation visible and keyboard accessible on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const primary = page.getByRole("navigation", { name: "Primary navigation" });
  const links = primary.getByRole("link");
  await expect(links).toHaveCount(3);
  for (const link of await links.all()) {
    await expect(link).toBeVisible();
  }

  const activity = primary.getByRole("link", { name: /Activity/ });
  await primary.getByRole("link", { name: "Library" }).focus();
  await page.keyboard.press("Tab");
  await expect(activity).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/activity$/);
  await expect(
    page.getByRole("navigation", { name: "Activity sections" }),
  ).toBeVisible();
});
