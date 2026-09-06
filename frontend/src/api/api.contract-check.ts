import { api, apiUrl } from "./client";
import { getBook, updateBook } from "./books";
import { uploadEpubs } from "./imports";

// Compiled by tsc, never executed. These expected errors prove the generated
// contract rejects drift in paths, verbs, parameters, bodies and responses.
export async function checkApiContract(): Promise<void> {
  await api.GET("/api/books/{book_id}", { params: { path: { book_id: 12 } } });
  await updateBook(12, { title: "Typed book", audiobook_enabled: true });
  await uploadEpubs([new File(["epub"], "book.epub")]);
  apiUrl("/api/books/{book_id}/download", { book_id: 12 });

  // @ts-expect-error Unknown endpoints cannot be called.
  await api.GET("/api/bookz");
  // @ts-expect-error This resource does not support POST.
  await api.POST("/api/books/{book_id}", { params: { path: { book_id: 12 } } });
  // @ts-expect-error Required path parameters cannot be omitted.
  await api.GET("/api/books/{book_id}");
  await api.GET("/api/books/{book_id}", {
    // @ts-expect-error Path IDs are numeric.
    params: { path: { book_id: "twelve" } },
  });
  await api.GET("/api/books/catalog", {
    // @ts-expect-error Catalog sorting is an API enum.
    params: { query: { sort_by: "popularity" } },
  });
  // @ts-expect-error JSON payload fields retain their backend types.
  await updateBook(12, { audiobook_enabled: "yes" });
  // @ts-expect-error Unknown JSON payload fields are rejected.
  await updateBook(12, { invented_field: true });
  // @ts-expect-error Multipart uploads require files rather than paths.
  await api.POST("/api/books/upload_epubs", { body: { files: ["book.epub"] } });
  // @ts-expect-error URL builders enforce backend path parameter names.
  apiUrl("/api/books/{book_id}/download", { id: 12 });

  const book = await getBook(12);
  if (book) {
    book.id.toFixed();
    // @ts-expect-error Responses retain their declared property types.
    book.id.toUpperCase();
    // @ts-expect-error Invented response properties cannot leak into the UI.
    void book.nonexistent_field;
  }
}
