async function parseError(response, fallbackMessage) {
  const payload = await response.json().catch(() => ({}));
  throw new Error(payload.detail || fallbackMessage);
}

export async function getJson(path, fallbackMessage = "Request failed") {
  const response = await fetch(path);
  if (!response.ok) {
    await parseError(response, fallbackMessage);
  }
  return response.json();
}

export async function getOptionalJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    return null;
  }
  return response.json();
}

export async function sendJson(path, { method = "POST", body, fallbackMessage = "Request failed" } = {}) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    await parseError(response, fallbackMessage);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export async function sendForm(path, body, { method = "POST", fallbackMessage = "Request failed" } = {}) {
  const response = await fetch(path, {
    method,
    body,
  });
  if (!response.ok) {
    await parseError(response, fallbackMessage);
  }
  return response.json();
}

export async function sendWithoutBody(path, { method = "POST", fallbackMessage = "Request failed" } = {}) {
  const response = await fetch(path, { method });
  if (!response.ok) {
    await parseError(response, fallbackMessage);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}
