import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import httpProxy from "http-proxy";
import handler from "serve-handler";

const host = process.env.HOST || "127.0.0.1";
const port = Number(process.env.PORT || 3000);
const apiTarget = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(__dirname, "..", "out");

const proxy = httpProxy.createProxyServer({
  target: apiTarget,
  changeOrigin: true,
  ws: true,
  xfwd: true,
  proxyTimeout: 10000,
  timeout: 10000,
});

proxy.on("error", (_error, _req, res) => {
  if (!res || typeof res.writeHead !== "function" || res.headersSent) {
    return;
  }
  res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ detail: "API proxy unavailable" }));
});

const server = http.createServer((req, res) => {
  const url = req.url || "/";
  if (url === "/api" || url.startsWith("/api/")) {
    proxy.web(req, res);
    return;
  }
  handler(req, res, {
    public: publicDir,
    cleanUrls: true,
  });
});

server.on("upgrade", (req, socket, head) => {
  const url = req.url || "/";
  if (url === "/api" || url.startsWith("/api/")) {
    proxy.ws(req, socket, head);
    return;
  }
  socket.destroy();
});

server.listen(port, host, () => {
  console.log(`Preview server listening on http://${host}:${port}`);
  console.log(`Proxying /api to ${apiTarget}`);
});
