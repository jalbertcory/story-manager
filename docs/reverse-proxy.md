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

## Authentik (or other forward auth) with app auth disabled

Running with `STORY_MANAGER_AUTH_MODE=disabled` is supported when a stronger identity layer sits in front of the app, such as an Authentik proxy outpost, Authelia, oauth2-proxy, or Cloudflare Access. In that mode Story Manager trusts every request that reaches `/` or `/api/*`, so the proxy is the only thing between the admin UI and the network. Set it up like this:

1. **Leave app auth off.** Unset `STORY_MANAGER_ADMIN_PASSWORD`, or set `STORY_MANAGER_AUTH_MODE=disabled` explicitly. Reader API keys keep protecting `/reader/*` either way.
2. **Make the proxy the only way in.** Do not publish port 8000 to the LAN or the internet. Put Story Manager and the proxy on the same Docker network and drop the `ports:` mapping, or bind it to loopback (`127.0.0.1:8000:8000`) when the proxy runs on the host. If neither is possible, firewall the port so only the proxy's address can reach it.
3. **Protect `/` and `/api/*` with forward auth.** Every admin request, including the frontend's API calls, must pass the outpost check.
4. **Leave `/reader/*` outside forward auth.** E-readers cannot complete an SSO login; they authenticate with their own reader API keys (Bearer or Basic). Forward `Authorization` unchanged on these routes.
5. **Keep `/health` internal.** The container health check calls it on `127.0.0.1` inside the container, so it never needs to go through the proxy.

Traefik labels for an Authentik embedded outpost (adjust the middleware address to your outpost):

```yaml
services:
  story-manager:
    # No `ports:` mapping; Traefik reaches the container on the shared network.
    environment:
      STORY_MANAGER_AUTH_MODE: disabled
    labels:
      traefik.enable: "true"
      traefik.http.services.story-manager.loadbalancer.server.port: "8000"

      # Admin UI and API: behind Authentik.
      traefik.http.routers.story-manager.rule: Host(`books.example.com`)
      traefik.http.routers.story-manager.entrypoints: websecure
      traefik.http.routers.story-manager.tls: "true"
      traefik.http.routers.story-manager.middlewares: authentik@docker
      traefik.http.middlewares.authentik.forwardauth.address: http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
      traefik.http.middlewares.authentik.forwardauth.trustForwardHeader: "true"
      traefik.http.middlewares.authentik.forwardauth.authResponseHeaders: X-authentik-username,X-authentik-email

      # Reader routes: reader API keys, no SSO. The longer rule wins over the router above.
      traefik.http.routers.story-manager-reader.rule: Host(`books.example.com`) && PathPrefix(`/reader/`)
      traefik.http.routers.story-manager-reader.entrypoints: websecure
      traefik.http.routers.story-manager-reader.tls: "true"
      traefik.http.routers.story-manager-reader.service: story-manager
```

The Nginx equivalent uses `auth_request` against the outpost for `location /` (which also covers `/api/`) and a plain `proxy_pass` for `location /reader/`, as in the sketch above. Authentik's "Forward auth (single application)" provider documentation has the full outpost snippet.

After changing the proxy, check both paths from outside your network: `https://books.example.com/` should redirect to the Authentik login, and `https://books.example.com/reader/...` with a reader key should work without one.
