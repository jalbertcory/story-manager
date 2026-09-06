import type { components } from "./api/schema";
export type Book = components["schemas"]["Book"];
export type CatalogBook = components["schemas"]["BookCatalogEntry"];
export type OpenBook = (book: Pick<Book, "id">, returnPath?: string) => void;
export type BookSectionChange = (section: string, tab?: string) => void;
export type LibraryValues = Record<string, string | number | null | undefined>;
export interface NavigationState {
  returnTo?: string;
  scrollY?: number;
  libraryScrollY?: number;
}
export type Navigate = (path: string, state?: NavigationState) => void;
