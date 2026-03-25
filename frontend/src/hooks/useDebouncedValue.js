import { useEffect, useState } from "react";

function useDebouncedValue(value, delayMs = 300) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    if (value === "") {
      setDebouncedValue(value);
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setDebouncedValue(value);
    }, delayMs);

    return () => window.clearTimeout(timeoutId);
  }, [value, delayMs]);

  return debouncedValue;
}

export default useDebouncedValue;
