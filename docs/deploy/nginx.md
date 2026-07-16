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
        # 避免 access log 记录 ?token=（可选）
        # access_log off;
    }

    location = /readyz {
        proxy_pass http://tg_signpulse;
        access_log off;
    }

    location = /healthz {
        proxy_pass http://tg_signpulse;
        access_log off;
    }
}
```

## 注意

- Dashboard 实时流使用 `EventSource`，JWT 在 **query** `token` 中；生产建议关闭该 path 的 access log，或改用仅内网可达的面板。
- `proxy_buffering off` 对 SSE 必需，否则浏览器长时间收不到事件。
- 与 Docker 联用时，将 `upstream` 指到 compose 服务名或宿主机映射端口。
