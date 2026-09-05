import { expect, test } from "@playwright/test";

test("groups pages under canonical destinations and preserves history", async ({
  page,
}) => {
  await page.goto("/activity");

  const primary = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(primary.getByRole("link")).toHaveCount(5);
  await expect(primary.getByRole("link", { name: "Library" })).toBeVisible();
  await expect(
    primary.getByRole("link", { name: "Background activity" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(primary.getByRole("link", { name: "Settings" })).toBeVisible();

  await page.getByLabel("Activity view").selectOption("processing");
  await expect(page).toHaveURL(/\/activity\/processing$/);
  await expect(
    page.getByRole("heading", { name: "Processing jobs" }),
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
    page.getByRole("heading", { name: "Reader API Keys", level: 2 }),
  ).toBeVisible();
  await expect(page.getByLabel("Library tool")).toHaveCount(0);

  await page.getByRole("link", { name: "← Settings", exact: true }).click();
  await page.getByRole("link", { name: /Storage cleanup/ }).click();
  await expect(page).toHaveURL(/\?section=storage$/);
  await expect(
    page.getByRole("heading", { name: "Storage Cleanup", level: 2 }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/settings$/);
  await page.goBack();
  await expect(page).toHaveURL(/\?section=reader-access$/);
  await expect(
    page.getByRole("heading", { name: "Reader API Keys", level: 2 }),
  ).toBeVisible();
});

test("keeps primary navigation visible and keyboard accessible on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const primary = page.getByRole("navigation", { name: "Primary navigation" });
  const links = primary.getByRole("link");
  await expect(links).toHaveCount(5);
  for (const link of await links.all()) {
    await expect(link).toBeVisible();
  }

  const activity = primary.getByRole("link", { name: "Background activity" });
  await primary.getByRole("link", { name: "Review suggestions" }).focus();
  await page.keyboard.press("Tab");
  await expect(activity).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/activity$/);
  await expect(page.getByLabel("Activity view")).toBeVisible();
});
