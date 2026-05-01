# Releasing

## Replay Receiver npm Package

The standalone replay receiver currently publishes as:

```bash
@moleculeagora/agora-replay
```

This is the active npm package for the public `npx` replay command. The package
is published from the Molecule-controlled npm user `moleculeagora`, with 2FA
enabled for authorization and writes.

`@moleculeagora` is a bootstrap scope, not an npm organization scope. The
original org-owned target, `@moleculeprotocol/agora-replay`, could not be
published because npm denied creation of the `moleculeprotocol` organization
scope. Keep this limitation explicit:

- npm user scopes do not provide team membership or per-person publisher roles.
- Future publishes depend on recovery access to the `moleculeagora` npm account.
- Recovery codes and account ownership must live in Molecule-controlled secret
  storage, not in this repository.

For `0.1.x` receiver releases, publish from a clean `main` checkout:

```bash
npm whoami
npm test
npm run check:replay-boundary
npm publish --access public
```

Publishing requires the npm security-key challenge for the `moleculeagora`
account. After publish, verify:

```bash
npm view @moleculeagora/agora-replay@<version> version
npx -y @moleculeagora/agora-replay@<version> --help
```

The desired long-term state is an organization-owned npm scope with CI-backed
publishing. Do not add additional npm package families under the personal scope
without first deciding whether the scope is permanent or migrating to an
organization-owned namespace.

## Official Runtime Image Provenance

The official scorer runtime image is published by `.github/workflows/publish.yml`
to `ghcr.io/moleculeprotocol/agora-scorer-compiled`. The workflow publishes a
GitHub/Sigstore provenance attestation for the pushed image digest and records
the verifier inputs in `official-runtime-release.json`.

Verify a published image before accepting a new Agora main runtime-profile
digest:

```bash
gh attestation verify \
  oci://ghcr.io/moleculeprotocol/agora-scorer-compiled@sha256:<digest> \
  --repo moleculeprotocol/agora-scorers \
  --signer-workflow moleculeprotocol/agora-scorers/.github/workflows/publish.yml \
  --source-digest <commit>
```

Use `digest`, `provenance.source_commit`, and `provenance.signer_workflow` from
`official-runtime-release.json`. Agora main owns the consuming digest-rotation
gate; this repo owns producing the attested image and release artifact metadata.
