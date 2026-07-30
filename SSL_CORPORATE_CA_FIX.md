# Fix: "Network error / SSL library failure" on a corporate VPN (macOS)

Apply this to the **Windows master source** of `byteplus_maya.py` so the next build
keeps the fix. Already applied to the Mac install on 2026-07-27 (v2.01).

## Symptom
```
Network error -- couldn't reach BytePlus
(A failure in the SSL library occurred (_ssl.c:1032))
```
…while the browser and `curl` work fine.

## Cause
A corporate TLS-inspection proxy (here: **SealSuite SWG**, on the ByteDance VPN)
re-signs every certificate with its own CA. macOS installs that CA in the
**keychain**, so curl/Safari trust it — but Maya's Python verifies against
**certifi's** bundle, which does not contain it, so every request fails.

Windows Python already reads the OS certificate store, so this is **macOS-only**.

## Fix
Replace `_ssl_context()` with the block below (adds two helpers above it).
Merges the macOS keychain CAs into the context, so it works with certificate
verification left **ON** — no need to untick "Verify SSL certificates".

```python
_OS_TRUST_PEM = None            # cached PEM of the OS trust store (macOS keychain)


def _os_trust_ca_pem() -> str:
    """macOS only: CA certificates from the system/login keychains, as PEM text.

    Maya's Python verifies against certifi's bundle, which does NOT contain CAs
    installed by an MDM or by a corporate TLS-inspection proxy (a VPN's secure
    web gateway). On such a network EVERY request dies with an SSL error even
    though curl/Safari work -- those trust the keychain. Windows Python already
    reads the OS certificate store, so this is macOS-only. Cached for the
    session; failing to read a keychain is harmless (returns '')."""
    global _OS_TRUST_PEM
    if _OS_TRUST_PEM is not None:
        return _OS_TRUST_PEM
    _OS_TRUST_PEM = ""
    if sys.platform != "darwin":
        return _OS_TRUST_PEM
    import subprocess
    chunks = []
    for kc in ("/Library/Keychains/System.keychain",
               os.path.expanduser("~/Library/Keychains/login.keychain-db")):
        if not os.path.exists(kc):
            continue
        try:
            out = subprocess.run(
                ["/usr/bin/security", "find-certificate", "-a", "-p", kc],
                capture_output=True, timeout=20)
            if out.stdout:
                chunks.append(out.stdout.decode("utf-8", "replace"))
        except Exception:
            pass
    _OS_TRUST_PEM = "\n".join(chunks)
    return _OS_TRUST_PEM


def _add_os_trust(ctx) -> int:
    """Add the OS-trust CAs to `ctx`. Loads the whole blob when it parses, else
    falls back to one certificate at a time so a single expired/odd keychain
    entry can't discard the rest. Returns how many were added."""
    pem = _os_trust_ca_pem()
    if not pem:
        return 0
    try:
        ctx.load_verify_locations(cadata=pem)
        return pem.count("BEGIN CERTIFICATE")
    except Exception:
        import re
        added = 0
        for cert in re.findall(
                "-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                pem, re.S):
            try:
                ctx.load_verify_locations(cadata=cert)
                added += 1
            except Exception:
                pass
        return added


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works inside Maya's bundled Python.

    Order: use `certifi`'s CA bundle if available (secure); else the system
    default; and only if CONFIG.SSL_VERIFY is False, fall back to an unverified
    context (last resort for Maya's CA-less Python on macOS). On macOS the
    keychain CAs are merged in as well, so a corporate TLS-inspecting VPN works
    with certificate verification left ON."""
    if not CONFIG.SSL_VERIFY:
        return ssl._create_unverified_context()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    _add_os_trust(ctx)          # macOS: also trust MDM / corporate-proxy CAs
    return ctx
```

## Verified (Maya 2027 Python 3.13.9, OpenSSL 3.5.4)
| | Result |
|---|---|
| certifi only (before) | FAIL — `SSLCertVerificationError` |
| certifi + keychain CAs (after) | **OK — TLS 1.3**, 13 CAs added, 0.11 s |
| Real HTTPS POST to the API | **HTTP 401** (i.e. reached it; only the key was missing) |

Cost is negligible: the keychain export takes ~0.03 s and is cached per session.

## Workaround if you can't rebuild
BYTEPLUS > Settings… > untick **Verify SSL certificates**. Works, but disables
certificate checking — the code fix above is preferable.
