export function compareSeriesBooks(left, right) {
  const leftIndex = left.series_index;
  const rightIndex = right.series_index;

  if (leftIndex != null && rightIndex != null && leftIndex !== rightIndex) {
    return Number(leftIndex) - Number(rightIndex);
  }
  if (leftIndex != null && rightIndex == null) return -1;
  if (leftIndex == null && rightIndex != null) return 1;

  const byTitle = left.title.localeCompare(right.title);
  if (byTitle !== 0) return byTitle;
  return left.id - right.id;
}

function compareCatalogBooks(left, right, sortBy, sortOrder) {
  const dir = sortOrder === "desc" ? -1 : 1;
  let comparison;
  if (sortBy === "author") {
    comparison = (left.author || "").localeCompare(right.author || "");
  } else if (sortBy === "word_count") {
    comparison =
      (left.current_word_count || 0) - (right.current_word_count || 0);
  } else if (sortBy === "updated_at") {
    comparison =
      new Date(left.updated_at || 0).getTime() -
      new Date(right.updated_at || 0).getTime();
  } else if (sortBy === "audiobook_enabled") {
    comparison =
      Number(Boolean(left.audiobook_enabled)) -
      Number(Boolean(right.audiobook_enabled));
  } else {
    comparison = (left.title || "").localeCompare(right.title || "");
  }

  if (comparison !== 0) return dir * comparison;
  const byTitle = (left.title || "").localeCompare(right.title || "");
  if (byTitle !== 0) return byTitle;
  return left.id - right.id;
}

export function buildCatalogGroups(books, sortBy = "title", sortOrder = "asc") {
  const seriesMap = {};
  const standaloneBooks = [];
  const webBooks = [];

  for (const book of books) {
    if (book.source_type === "web" && !book.download_status) {
      webBooks.push(book);
    }

    if (book.series && !book.download_status) {
      if (!seriesMap[book.series]) {
        seriesMap[book.series] = [];
      }
      seriesMap[book.series].push(book);
    } else if (book.source_type !== "web") {
      standaloneBooks.push(book);
    }
  }

  for (const seriesBooks of Object.values(seriesMap)) {
    seriesBooks.sort(compareSeriesBooks);
  }

  standaloneBooks.sort((left, right) =>
    compareCatalogBooks(left, right, sortBy, sortOrder),
  );
  webBooks.sort((left, right) =>
    compareCatalogBooks(left, right, sortBy, sortOrder),
  );

  const dir = sortOrder === "desc" ? -1 : 1;
  const sortedSeries = Object.keys(seriesMap).sort((a, b) => {
    const booksA = seriesMap[a];
    const booksB = seriesMap[b];
    if (sortBy === "author") {
      return (
        dir * (booksA[0].author || "").localeCompare(booksB[0].author || "")
      );
    }
    if (sortBy === "word_count") {
      const wcA = booksA.reduce(
        (sum, bk) => sum + (bk.current_word_count || 0),
        0,
      );
      const wcB = booksB.reduce(
        (sum, bk) => sum + (bk.current_word_count || 0),
        0,
      );
      return dir * (wcA - wcB);
    }
    if (sortBy === "updated_at") {
      const latestA = Math.max(
        ...booksA.map((bk) => new Date(bk.updated_at || 0).getTime()),
      );
      const latestB = Math.max(
        ...booksB.map((bk) => new Date(bk.updated_at || 0).getTime()),
      );
      return dir * (latestA - latestB);
    }
    if (sortBy === "audiobook_enabled") {
      const enabledA = booksA.some((book) => book.audiobook_enabled);
      const enabledB = booksB.some((book) => book.audiobook_enabled);
      const byEnabled = Number(enabledA) - Number(enabledB);
      return byEnabled !== 0 ? dir * byEnabled : a.localeCompare(b);
    }
    return dir * a.localeCompare(b);
  });

  return {
    seriesMap,
    sortedSeries,
    standaloneBooks,
    webBooks,
    counts: {
      series: sortedSeries.length,
      standalone: standaloneBooks.length,
      web: webBooks.length,
    },
  };
}
