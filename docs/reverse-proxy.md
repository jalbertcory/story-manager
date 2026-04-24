# Reverse Proxy Safety

Story Manager can protect the admin web UI and `/api/*` routes with built-in password auth by setting `STORY_MANAGER_AUTH_MODE=password` and `STORY_MANAGER_ADMIN_PASSWORD`.

If you use a reverse proxy or Cloudflare Access as the admin auth layer, set `STORY_MANAGER_AUTH_MODE=disabled` and keep the proxy rules strict. Reader API keys only protect `/reader/*`; they are not admin credentials.

Safe deployment guidance:

- Expose `/reader/*` publicly only if needed for e-readers.
- Keep `/` and `/api/*` behind built-in password auth, a VPN, Tailscale, local network, or proxy authentication.
- Terminate TLS at the proxy and redirect HTTP to HTTPS.
- Preserve the `Authorization` header so Bearer and Basic auth work for `/reader/*`.
- Disable proxy caching for `/reader/*` responses that contain private library metadata.
- Set a reasonable request body limit on admin upload routes.

Recommended layout:

- Public: `/reader/*`
- Private: `/`, `/api/*`

Example Nginx sketch:

```nginx
server {
    listen 443 ssl http2;
    server_name books.example.com;

    ssl_certificate /etc/letsencrypt/live/books.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/books.example.com/privkey.pem;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;

    location /reader/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;
        add_header Cache-Control "private, no-store";
    }

    location /api/ {
        allow 192.168.0.0/16;
        allow 10.0.0.0/8;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }

    location / {
        allow 192.168.0.0/16;
        allow 10.0.0.0/8;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

If the admin UI needs to be reachable over the internet, put `/` and `/api/*` behind built-in password auth or a real upstream authentication layer first.
