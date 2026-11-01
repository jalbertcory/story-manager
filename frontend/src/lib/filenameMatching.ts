import type { CatalogBook } from "../types";

// Matches a picked audiobook to a library book by its file and folder names,
// and ranks the library search shown when the user picks a book by hand.

type MatchableBook = Pick<CatalogBook, "title" | "author">;
type NamedFile = Pick<File, "name" | "webkitRelativePath">;

const MATCH_STOP_WORDS = new Set([
  "and",
  "book",
  "edition",
  "series",
  "the",
  "volume",
]);

export function normalizeMatchText(value: string | null | undefined) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function bookLabel(book: MatchableBook) {
  return `${book.title} — ${book.author || "Unknown author"}`;
}

// The full title, plus the title without any subtitle or parenthetical.
function titleVariants(title: string) {
  const full = normalizeMatchText(title);
  const titleText = String(title || "");
  const primary = normalizeMatchText(titleText.split(/[:([]/, 1)[0] ?? "");
  return [...new Set([full, primary].filter(Boolean))];
}

function significantTokens(value: string | null | undefined) {
  return normalizeMatchText(value)
    .split(" ")
    .filter((token) => token.length > 2 && !MATCH_STOP_WORDS.has(token));
}

export function scoreFilenameMatch(book: MatchableBook, fileText: string) {
  const normalizedFile = normalizeMatchText(fileText);
  const variants = titleVariants(book.title);
  let score = 0;

  variants.forEach((variant, index) => {
    if (variant.length >= 4 && normalizedFile.includes(variant)) {
      score = Math.max(score, (index === 0 ? 1000 : 900) + variant.length);
    }
  });

  const titleTokens = significantTokens(book.title);
  const fileTokens = new Set(significantTokens(fileText));
  const matchedTokens = titleTokens.filter((token) => fileTokens.has(token));
  const coverage = titleTokens.length
    ? matchedTokens.length / titleTokens.length
    : 0;
  if (matchedTokens.length >= 2 && coverage >= 0.7) {
    score = Math.max(score, 500 + coverage * 100 + matchedTokens.length);
  }

  if (score > 0) {
    const authorTokens = significantTokens(book.author);
    score += authorTokens.filter((token) => fileTokens.has(token)).length * 10;
  }
  return score;
}

// The single best match, or null when nothing matches or two books are too
// close to call.
export function findFilenameBookMatch<Book extends MatchableBook>(
  files: NamedFile[],
  catalog: Book[],
) {
  const fileText = files
    .map((file) => file.webkitRelativePath || file.name)
    .join(" ");
  const candidates = catalog
    .map((book) => ({ book, score: scoreFilenameMatch(book, fileText) }))
    .filter((candidate) => candidate.score > 0)
    .sort((left, right) => right.score - left.score);

  const [best, runnerUp] = candidates;
  if (!best) return null;
  if (runnerUp && best.score - runnerUp.score < 5) {
    return null;
  }
  return best.book;
}

export function scoreBookSearch(book: MatchableBook, normalizedQuery: string) {
  const title = normalizeMatchText(book.title);
  const author = normalizeMatchText(book.author);
  if (title === normalizedQuery) return 100;
  if (title.startsWith(normalizedQuery)) return 90;
  if (title.includes(normalizedQuery)) return 80;
  if (author === normalizedQuery) return 70;
  if (author.startsWith(normalizedQuery)) return 60;
  if (author.includes(normalizedQuery)) return 50;
  return 0;
}
