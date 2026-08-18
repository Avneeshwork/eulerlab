# Runbook — `make sync-cloud` problems

**What it does.** Mirrors `data/landing/` to Backblaze B2. Local disk is the
working copy; B2 is the second copy that survives the laptop. See ADR-007.

---

## "the B2 key cannot read ... it needs the readFiles and listFiles capabilities"

**Symptom.** `make sync-cloud` exits immediately with that message.

**Cause.** The B2 application key can write but not read. It sounds safer and it
is actively harmful here.

**Why it matters more than it looks.** The sync decides what to upload by asking
"is this object already there, with a matching hash?". A key that cannot read
gets AccessDenied for every such question. Read naively, that means "not there",
so the sync re-uploads the entire landing zone on every run — and reports
success while doing it. Bandwidth and B2 transaction costs grow silently, and
nothing is ever actually verified. The preflight check exists so this fails on
line one instead.

**Fix.** Recreate the application key in the B2 console with, at minimum:

| Capability | Why |
|---|---|
| `writeFiles` | to upload |
| `readFiles` | to check the recorded SHA-256 before uploading |
| `listFiles` | to enumerate what is already there |

Scope it to the landing bucket, not the whole account. Then update `B2_KEY_ID`
and `B2_APP_KEY` in `.env` — **never** in `.env.example`, which is committed.

**On `deleteFiles`:** leave it off. The landing zone is append-only by design,
the sync never deletes, and a key that cannot delete cannot be used to destroy
the backup. If your current key has it, that is a reason to replace the key.

**Never use the account Master Application Key.** It has full account rights,
cannot be scoped to one bucket, and cannot be revoked without disrupting
everything else using it.

---

## Checking what the key can actually do

```bash
set -a; . ./.env; set +a
python3 -c "
import base64, json, os, urllib.request
t = base64.b64encode(f\"{os.environ['B2_KEY_ID']}:{os.environ['B2_APP_KEY']}\".encode()).decode()
r = urllib.request.Request('https://api.backblazeb2.com/b2api/v3/b2_authorize_account',
                           headers={'Authorization': f'Basic {t}'})
a = json.load(urllib.request.urlopen(r))['apiInfo']['storageApi']
print('endpoint:', a['s3ApiUrl']); print('bucket  :', a.get('bucketName'))
print('can     :', ', '.join(sorted(a['capabilities'])))"
```

This also prints the correct `endpoint_url` and `bucket` for
`config/storage.yaml`, so there is no need to guess them from the console.

---

## What the sync actually compares

Two modes, because they answer different questions at very different costs.

| Command | Compares | Cost | Use |
|---|---|---|---|
| `make sync-cloud` | object **size** against the manifest | one paginated LIST for the whole bucket — about 3 seconds for thousands of objects | every time |
| `make sync-cloud VERIFY=1` | recorded **SHA-256** of every object | one request per object — minutes, not seconds | occasional audit |

Size equality is a weak check: it catches truncation and absence, but not a
corruption that happens to preserve length. The strong check exists and is
exact; it is simply not something every routine sync should pay for. Same split
as `make check-landing` for the local copy.

This started as one HEAD per file for *every* sync, which took roughly ten
minutes against ~1,700 objects and would have been unusable at 5,800. If the
sync ever feels slow again, check that it is not silently falling back to
per-object requests.

---

## "MISMATCHED — in the bucket with a different hash"

An object exists at our key with a SHA-256 that is not the one in the manifest.
The sync **does not overwrite it** and reports it instead.

This should never happen. It means either the local file changed after landing
(run `make check-landing`) or something else wrote to that key. Investigate
before touching it — overwriting destroys the evidence of whichever it was.

---

## Sync appears to hang with no output

Python buffers stdout when it is not attached to a terminal, so a backgrounded
sync prints nothing until it exits. It is not stuck. Either wait, or run it in
the foreground. Progress cannot be checked by listing the bucket unless the key
has `listFiles`.

---

## A dataset has zero objects in the bucket

**Symptom.** Everything looks fine locally, `make sync-cloud` reports success,
but a whole dataset is missing from B2.

**Cause, seen twice.** `sync_cloud` used to mirror a hardcoded list of trees.
Adding a new dataset without also registering it there meant it was silently
never backed up — participant-OI hit this, then fundamentals hit it again with
757 files and zero objects in the bucket.

**Fixed.** Trees are now *discovered* under `data/landing/`, so a new dataset
is mirrored automatically. There is no list to forget to update.

**Related and worse:** `--dry-run` used to return before the tree loop ran, so
it reported `would upload: 0` on the `nse` tree alone and looked perfectly
clean while 10,176 files across two other trees were unsynced. A check that
reassures you while the thing it checks is broken is worse than no check at
all. Dry-run now covers every tree.

**How to confirm coverage yourself:**

```bash
make sync-cloud DRY=1
```

It prints one section per dataset tree. If a dataset you expect is not listed,
it is not being mirrored.

## Prevention

`tests/test_no_secrets.py` fails the build if any value in `.env.example` is
non-empty, which is how credentials got committed once already.
