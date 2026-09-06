import DOMPurify from "dompurify";

function getBodyContent(html: string) {
  const match = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  return match ? match[1] : html;
}

export function sanitizeChapterHtml(html: string) {
  return DOMPurify.sanitize(getBodyContent(html), {
    USE_PROFILES: { html: true },
  });
}
