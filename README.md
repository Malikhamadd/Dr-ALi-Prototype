# Dr-ALi-Prototype

This repo contains a local static mirror of:

- https://videa-saversion.webflow.io/

The mirrored site lives here:

- mirror/videa-saversion.webflow.io/

## Preview locally

From the repo root:

```bash
python3 -m http.server 8080 --directory mirror/videa-saversion.webflow.io
```

Then open:

- http://localhost:8080/

## Re-mirror (refresh from Webflow)

```bash
rm -rf mirror && mkdir -p mirror
wget --mirror --page-requisites --adjust-extension --convert-links --no-parent \
	--restrict-file-names=windows -e robots=off --wait=1 --random-wait \
	--user-agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36" \
	--directory-prefix=mirror https://videa-saversion.webflow.io/

# Post-process: download external assets + rewrite links for offline editing
python3 tools/mirror_webflow.py mirror/videa-saversion.webflow.io
```

Note: Only mirror sites you own or have permission to duplicate.