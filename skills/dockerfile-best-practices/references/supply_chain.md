# Supply Chain: Attestations, SBOM, Provenance, Signing

An image is a claim. Attestations are what turn it into a claim someone else can
check. This is the layer that answers "what is actually in this image, and what
built it", and it is entirely a build-time and registry concern: nothing in the
Dockerfile produces it.

## Building with attestations

```bash
docker buildx build \
  --provenance=mode=max \
  --sbom=true \
  --push -t registry.example.com/app:1.0.0 .
```

- `--sbom=true` attaches a Software Bill of Materials: the packages BuildKit
  detected in the result.
- `--provenance=mode=max` attaches a SLSA provenance attestation: what built
  this, from which source, with which materials, in which steps.

Both ride alongside the image in the registry as separate manifests referenced
by an OCI image index, not as layers.

### Attestations require pushing to a registry

This is the single thing that trips people most often. Attestations **do not
survive `--load`**. The local image store cannot represent them: `--load` and the
`docker` exporter both drop them silently, with no error, and the image looks
built. Only when you go looking for the attestation later do you find nothing.

If you build with `--load` to test and then `--push` the "same" image, the pushed
image is a fresh build and the loaded one never had attestations at all. Push
directly, or export to a registry, or accept that you have no attestations.

## GitHub Actions

`docker/build-push-action` adds provenance attestations by default, and its
default depends on repository visibility:

- **Public repository**: provenance `mode=max` is added automatically.
- **Private repository**: provenance `mode=min` is added automatically.
- **`load: true` or the `docker` exporter**: no attestations are added at all,
  for the reason above.

SBOM is opt-in: set `sbom: true` on the action.

Source: <https://docs.docker.com/build/ci/github-actions/attestations/>

### A build argument is not a secret, and provenance is the second reason why

SKILL.md rule 5 already says: never pass a secret through `--build-arg`, because
`ARG` values persist in image history and anyone with the image can read them
back. That argument is correct, and it is the one everybody knows.

Here is the second one, which almost nobody knows: **`mode=max` provenance
records the values of build arguments.** So does the full base64-encoded
Dockerfile it embeds. A secret passed via `--build-arg` is therefore published
into the provenance attestation, as structured, indexed, trivially queryable JSON
attached to your image in the registry.

Now combine that with the defaults above. `docker/build-push-action` applies
`mode=max` automatically to **public** repositories. The exact case where the
blast radius is largest is the exact case where the default is most verbose. A
team that has never heard of provenance, building a public repo in GitHub
Actions, passing a token via `--build-arg`, is publishing that token in a machine
readable attestation and has no idea the file exists.

`mode=min` does not include build argument values, secret identities, or the LLB
definition, which is why Docker documents it as safe for all builds. That is a
mitigation, not a fix: `ARG` still lands in image history regardless of mode.

The fix is the same as it always was:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim

RUN --mount=type=secret,id=pip_token \
    PIP_INDEX_URL="https://$(cat /run/secrets/pip_token)@pypi.example.com/simple" \
    pip install --no-cache-dir private-package
```

Secret mounts never enter a layer, never enter image history, and are never
included in provenance attestations. If a secret has already gone out through a
build argument, rotate it. It is in a registry, in an artifact people copy
around, and possibly in a public one.

Sources: <https://docs.docker.com/build/metadata/attestations/slsa-provenance/>

## Reproducible builds

Timestamps are what usually break byte-for-byte reproducibility: every file
written during the build carries the wall clock time it was written. Set a fixed
epoch and have the exporter rewrite them.

```bash
SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct) docker buildx build \
  --output type=image,name=registry.example.com/app,push=true,rewrite-timestamp=true .
```

- `SOURCE_DATE_EPOCH` propagation from the host environment into the build:
  **Buildx 0.10+** (and `buildctl` on BuildKit 0.13+). Below that, pass it
  explicitly as a build argument.
- `rewrite-timestamp=true` on the image exporter: **BuildKit v0.13+**. BuildKit
  v0.11 handled only OCI/image metadata timestamps, not the file timestamps
  inside layers, which is why v0.11-era reproducibility advice does not get you
  a matching digest.

### Declaring the epoch in the Dockerfile

Since frontend 1.23 the Dockerfile can carry its own default in the global
scope, so a plain `docker build` is reproducible without anyone exporting a
variable. A caller's `--build-arg` or `$SOURCE_DATE_EPOCH` still wins.

```dockerfile
# Fragment: global scope, before the first FROM
ARG SOURCE_DATE_EPOCH=context
```

Two special values arrived in 1.24:

- **`context`** resolves from the main build context. Measured: a git URL
  context gives the commit time to the second. Per the docs, an HTTP context
  gives `Last-Modified` (or the newest archive entry). A **local** context leaves it
  unset and the image gets the wall clock, because files on disk have no stable
  timestamp. So `context` makes CI builds from a git URL reproducible and does
  nothing for `docker build .` on a laptop. That is by design, not a bug.
- **`<stage>`** takes it from a named stage, which must be `FROM scratch` with a
  single remote `ADD` (git or HTTP). Use it when the artifact you package, not
  the repository, should date the image.

A git URL context also accepts `?mtime=commit` (1.23+), which sets the checked
out files to the commit time. It is the default when `SOURCE_DATE_EPOCH` is set
on a git context, so you rarely write it.

`rewrite-timestamp=true` is still required for the file timestamps inside
layers. The epoch alone only fixes the image config and history.

Source: <https://github.com/moby/buildkit/blob/master/docs/build-repro.md>

## The frontend is part of the supply chain

`# syntax=docker/dockerfile:1` pulls the Dockerfile frontend, an image that
parses your Dockerfile and decides what gets built. Since 1.21 the frontend
images are signed, built on Docker's GitHub builder. A
policy that verifies base images and ignores the frontend is verifying the
ingredients and trusting the cook unseen. Verify both with the same tooling, or
at least know the frontend is in scope.

## Signing

```bash
cosign sign --key cosign.key registry.example.com/app@sha256:<digest>
```

**Sign a digest, never a tag.** A tag is a mutable pointer: signing
`app:1.0.0` records a signature against whatever that name resolved to at that
instant, and the name can be repointed to different bytes five minutes later
without invalidating anything. The signature would then vouch for content that no
longer exists at the reference it names, which is to say it vouches for nothing.
A digest is the content. Signing it is a statement about bytes, and bytes do not
move. Take the digest from the push output (or `docker buildx imagetools inspect`)
and sign that; tag it separately for humans.

Signing is orthogonal to how you chose the base image tag in your `FROM`. It says
"we produced this artifact", not "we know what we built on top of". Do not
conflate the two.

## The connection to pinning

`best_practices.md` makes the point that "receives security patches" and
"reproducible" are properties of a **process**, not of a tag string, and that a
digest in a `FROM` without renewal automation is just a tag that rots quietly.
Provenance is the other half of that argument.

A `mode=min` provenance attestation already includes the build **materials**: the
resolved digest of every base image and frontend the build actually consumed,
recorded at the moment it was consumed, whether your `FROM` named a digest or
not. So the reproducibility question stops being "did I type a digest into my
Dockerfile" and becomes "does my build record what it resolved". A build with
provenance can answer, six months later and with evidence, what
`python:3.14-slim` meant on the day it ran. A Dockerfile with a hardcoded digest
and no attestations can only tell you what someone once intended it to mean.

This is why the doctrine is a readable tag plus a process rather than a digest
string. The digest still matters, enormously. It just belongs in build metadata
that is produced automatically on every build, not hand-copied into a source file
where nobody renews it.
