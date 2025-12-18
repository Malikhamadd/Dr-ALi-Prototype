import http from "node:http";
import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";

const siteRoot = path.resolve("mirror/videa-saversion.webflow.io");
const port = Number(process.env.PORT || 8080);

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".eot": "application/vnd.ms-fontobject",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".pdf": "application/pdf",
};

function send(res, status, body, headers = {}) {
  res.writeHead(status, {
    "Cache-Control": "public, max-age=3600",
    ...headers,
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    // Decode and normalize path; prevent path traversal.
    const decodedPath = decodeURIComponent(url.pathname);
    const safePath = decodedPath.replace(/\\/g, "/");

    let candidate = safePath;
    if (candidate.endsWith("/")) candidate += "index.html";

    const absPath = path.resolve(siteRoot, candidate.replace(/^\//, ""));
    if (!absPath.startsWith(siteRoot + path.sep) && absPath !== siteRoot) {
      return send(res, 403, "Forbidden\n", { "Content-Type": "text/plain; charset=utf-8" });
    }

    let stat;
    try {
      stat = await fs.stat(absPath);
    } catch {
      return send(res, 404, "Not Found\n", { "Content-Type": "text/plain; charset=utf-8" });
    }

    if (stat.isDirectory()) {
      const indexPath = path.join(absPath, "index.html");
      try {
        await fs.access(indexPath);
        res.writeHead(302, { Location: url.pathname.replace(/\/$/, "") + "/" });
        return res.end();
      } catch {
        return send(res, 404, "Not Found\n", { "Content-Type": "text/plain; charset=utf-8" });
      }
    }

    const ext = path.extname(absPath).toLowerCase();
    const contentType = CONTENT_TYPES[ext] || "application/octet-stream";

    res.writeHead(200, {
      "Content-Type": contentType,
      "Cache-Control": ext === ".html" ? "no-cache" : "public, max-age=31536000, immutable",
    });

    createReadStream(absPath).pipe(res);
  } catch (e) {
    send(res, 500, "Internal Server Error\n", { "Content-Type": "text/plain; charset=utf-8" });
  }
});

server.listen(port, "0.0.0.0", () => {
  // eslint-disable-next-line no-console
  console.log(`Serving ${siteRoot} on port ${port}`);
});
