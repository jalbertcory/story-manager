# Reverse Proxy Safety

Story Manager does not yet have built-in user login for the admin web UI. The web UI and `/api/*` routes should be treated as trusted admin surfaces.

Safe deployment guidance:

- Expose `/reader/*` publicly only if needed for e-readers.
- Keep `/` and `/api/*` behind a VPN, Tailscale, local network, or proxy authentication.
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

If the admin UI needs to be reachable over the internet, put `/` and `/api/*` behind a real authentication layer first. Reader API keys are not a substitute for admin authentication.
