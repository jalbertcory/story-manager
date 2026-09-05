import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";

// Build distinct EPUBs using only Python's standard library, including in CI.
function libraryArchive(series: string) {
  return execFileSync("python3", [
    "-c",
    `
import io, sys, zipfile, xml.etree.ElementTree as ET
series = sys.argv[1]
archive = io.BytesIO()
with zipfile.ZipFile('test.epub') as source, zipfile.ZipFile(archive, 'w') as target:
    for i in range(32):
        book = io.BytesIO()
        with zipfile.ZipFile(book, 'w') as output:
            for name in source.namelist():
                content = source.read(name)
                if name.endswith('.opf'):
                    root = ET.fromstring(content)
                    ns = {'opf': 'http://www.idpf.org/2007/opf', 'dc': 'http://purl.org/dc/elements/1.1/'}
                    metadata = root.find('opf:metadata', ns)
                    metadata.find('dc:title', ns).text = series + ' Volume ' + str(i).zfill(2)
                    metadata.find('dc:identifier', ns).text = series + '-' + str(i)
                    for meta in list(metadata):
                        if meta.tag.endswith('meta') and meta.attrib.get('name', '').startswith('calibre:series'):
                            metadata.remove(meta)
                    ET.SubElement(metadata, '{http://www.idpf.org/2007/opf}meta', name='calibre:series', content=series)
                    ET.SubElement(metadata, '{http://www.idpf.org/2007/opf}meta', name='calibre:series_index', content=str(i / 2))
                    ET.SubElement(metadata, '{http://purl.org/dc/elements/1.1/}subject').text = 'PaginationTest'
                    content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                output.writestr(name, content)
        target.writestr(str(i) + '.epub', book.getvalue())
sys.stdout.buffer.write(archive.getvalue())
`,
    series,
  ]);
}

test("filters, saves a view, pages a real series and preserves the return location", async ({
  page,
}) => {
  test.setTimeout(120000);
  const series = `Library QA ${Date.now()}`;
  const ids: number[] = [];
  try {
    const imported = await page.request.post("/api/books/upload_epubs", {
      multipart: {
        files: {
          name: "library.zip",
          mimeType: "application/zip",
          buffer: libraryArchive(series),
        },
      },
    });
    expect(imported.ok()).toBeTruthy();
    const results = await imported.json();
    ids.push(
      ...results
        .filter((item: { book?: { id: number } }) => item.book)
        .map((item: { book: { id: number } }) => item.book.id),
    );
    expect(ids).toHaveLength(32);
    // Set fractional order through the supported API so this test does not
    // depend on EPUB metadata inference or title-based series detection.
    for (let i = 0; i < results.length; i++) {
      const updated = await page.request.put(
        `/api/books/${results[i].book.id}`,
        {
          data: { series, series_index: i / 2 },
        },
      );
      expect(updated.ok()).toBeTruthy();
    }
    await page.goto(`/?q=${encodeURIComponent(series)}`);
    await expect(page.getByLabel("Library genre")).toBeHidden();
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await page.getByLabel("Library genre").selectOption("PaginationTest");
    await page.getByLabel("Library audio").selectOption("unplayable");
    await page.getByText("Saved views", { exact: true }).click();
    await page.getByLabel("View name").fill("QA reading list");
    await page.getByRole("button", { name: "Save current view" }).click();
    await page
      .getByRole("link", { name: new RegExp(`${series}.*32 books`) })
      .click();
    await expect(
      page.getByText("Showing 30 of 32 books", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Library genre")).toHaveValue(
      "PaginationTest",
    );
    await expect(page.getByLabel("Library audio")).toHaveValue("unplayable");
    await page.getByRole("button", { name: "Load more books" }).click();
    await expect(
      page.getByText("Showing 32 of 32 books", { exact: true }),
    ).toBeVisible();
    const titles = await page.locator(".book-row-title").allTextContents();
    expect(titles).toEqual(
      Array.from(
        { length: 32 },
        (_, i) => `${series} Volume ${String(i).padStart(2, "0")}`,
      ),
    );
    await page
      .getByRole("link", { name: new RegExp(`${series} Volume 31`) })
      .click();
    await page
      .getByRole("button", { name: "Back to library", exact: false })
      .click();
    await expect(page.getByLabel("Library genre")).toHaveValue(
      "PaginationTest",
    );
    await page.reload();
    await expect(page.getByLabel("Library genre")).toBeHidden();
    await page
      .getByRole("button", { name: "Filters (2)", exact: true })
      .click();
    await expect(page.getByLabel("Library audio")).toHaveValue("unplayable");
    await page.getByText("Saved views", { exact: true }).click();
    await page
      .getByRole("button", { name: "QA reading list", exact: true })
      .click();
    await expect(page).not.toHaveURL(/series=/);
    await expect(page.getByLabel("Library genre")).toHaveValue(
      "PaginationTest",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByLabel("Library audio")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    // Exercise PostgreSQL group cursors as well as book cursors.
    for (let i = 0; i < ids.length; i++) {
      const updated = await page.request.put(`/api/books/${ids[i]}`, {
        data: { series: `${series} Group ${String(i).padStart(2, "0")}` },
      });
      expect(updated.ok()).toBeTruthy();
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(
      `/?q=${encodeURIComponent(series)}&sort=updated_at&order=desc`,
    );
    await expect(
      page.getByText("Showing 30 of 32 groups", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Load more groups" }).click();
    await expect(
      page.getByText("Showing 32 of 32 groups", { exact: true }),
    ).toBeVisible();
    const names = await page.locator(".library-group-row h3").allTextContents();
    expect(new Set(names).size).toBe(32);
  } finally {
    for (const id of ids)
      await page.request.delete(`/api/books/${id}?permanent=true`);
  }
});

test("retries from Needs Attention and displays a failed recovery without leaving the page", async ({
  page,
}) => {
  const empty = { count: 0, items: [] };
  await page.route("**/api/dashboard/attention?*", (route) =>
    route.fulfill({
      json: {
        total_count: 1,
        failed_jobs: {
          count: 1,
          items: [
            {
              id: 812,
              job_type: "refresh_book",
              book_title: "Offline novel",
              error: "Source unavailable",
            },
          ],
        },
        failed_refreshes: empty,
        missing_covers: empty,
        broken_files: empty,
        stale_audiobooks: empty,
        metadata_proposals: empty,
      },
    }),
  );
  await page.route("**/api/processing/jobs/812/retry", (route) =>
    route.fulfill({ json: { id: 812, status: "queued" } }),
  );
  await page.route("**/api/processing/jobs/812", (route) =>
    route.fulfill({
      json: { id: 812, status: "error", error: "Source is still unavailable" },
    }),
  );
  await page.goto("/activity");
  await page
    .getByRole("button", { name: "Retry task for Offline novel" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Source is still unavailable",
  );
  await expect(page).toHaveURL(/\/activity$/);
  await expect(
    page.getByRole("button", { name: "Retry task for Offline novel" }),
  ).toBeEnabled();
});
