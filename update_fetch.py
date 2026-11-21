"""Short-lived, bounded HTTPS fetcher used by the desktop update UI."""
import argparse
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

MAX_TOTAL = 80 * 1024 * 1024
MAX_METADATA = 2 * 1024 * 1024
ALLOWED_HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com'}


class FetchValidationError(ValueError):
    pass


class LimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 2
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
            raise FetchValidationError('Untrusted update redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, destination=None):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
        raise FetchValidationError('Untrusted update URL')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'ClaudePet', 'Accept': 'application/vnd.github+json',
    })
    opener = urllib.request.build_opener(LimitedRedirectHandler())
    with opener.open(request, timeout=25 if destination else 8) as response:
        if urllib.parse.urlparse(response.geturl()).hostname not in ALLOWED_HOSTS:
            raise FetchValidationError('Untrusted update response host')
        if destination:
            total = 0
            with Path(destination).open('wb') as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_TOTAL:
                        raise FetchValidationError('Package exceeds size limit')
                    output.write(block)
            return
        payload = response.read(MAX_METADATA + 1)
        if len(payload) > MAX_METADATA:
            raise FetchValidationError('Release metadata too large')
        return json.loads(payload.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = fetch(args.url, args.output)
        if args.output is None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    except FetchValidationError as exc:
        sys.stderr.write(str(exc))
        return 2
    except Exception as exc:
        # Keep diagnostics bounded and avoid exposing URLs or response contents.
        sys.stderr.write(type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
