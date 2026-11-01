import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "./lib/queryClient";

// The app's client (with its global 401 handling), minus retries so failures
// surface immediately.
const createTestQueryClient = () => {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return client;
};

export const renderWithClient = (ui) => {
  const testQueryClient = createTestQueryClient();
  const { rerender, ...result } = render(
    <QueryClientProvider client={testQueryClient}>{ui}</QueryClientProvider>,
  );
  return {
    ...result,
    rerender: (rerenderUi) =>
      rerender(
        <QueryClientProvider client={testQueryClient}>
          {rerenderUi}
        </QueryClientProvider>,
      ),
  };
};
