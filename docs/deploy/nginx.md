# Nginx 反向代理（生产）

用于在容器前终止 TLS、隐藏内部端口，并正确转发 WebSocket / SSE。

## 最小配置示例

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream tg_signpulse {
    server 127.0.0.1:8080;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name panel.example.com;

    # ssl_certificate     /etc/ssl/certs/panel.fullchain.pem;
    # ssl_certificate_key /etc/ssl/private/panel.key;

    client_max_body_size 20m;

    # 默认 API / 静态
    location / {
        proxy_pass http://tg_signpulse;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }

    # 任务日志 WebSocket
    location ~ ^/api/sign-tasks/ws/ {
        proxy_pass http://tg_signpulse;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # SSE 事件流（Dashboard 实时日志）
    location /api/events/ {
        proxy_pass http://tg_signpulse;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 3600s;
        # SSE 使用 60s 一次性 ticket 票据接入，长效 JWT 不会在 URL 中暴露
    }

    location = /readyz {
        proxy_pass http://tg_signpulse;
        access_log off;
    }

    location = /healthz {
        proxy_pass http://tg_signpulse;
        access_log off;
    }

    # 生产安全加固：屏蔽文档与规范端点探测（纵深防御，可选）
    # location ~ ^/(docs|redoc|openapi\.json) {
    #     return 404;
    # }
}
```

## 注意

- Dashboard 实时流使用 `EventSource`，前端先通过 Bearer JWT 请求 `POST /api/events/ticket` 换取 60 秒有效的一次性接入票据，再通过 `?ticket=` 建立 SSE 流。长效 JWT 不会落在 URL 或 access log 中。
- `proxy_buffering off` 对 SSE 必需，否则浏览器长时间收不到事件。
- 与 Docker 联用时，将 `upstream` 指到 compose 服务名或宿主机映射端口。
