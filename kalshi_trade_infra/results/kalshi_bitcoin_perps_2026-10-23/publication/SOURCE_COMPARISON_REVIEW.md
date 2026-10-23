# Installed source comparison — 2026-10-23

Offline, read-only review of the canonical `READINESS_39884723368.json` in the feature worktree. No production, provider, database, deployment, service, or settings operation was performed by this reviewer. Only this review file was created.

**A whole-main replacement is not yet proven to preserve installed work.** Of 21 installed paths differing from base main, 11 have exact local Git blob matches; 10 have no exact byte match in the local object database or inspected source caches. The latter are unresolved provenance, not proof of unpublished changes. Eight of those are application files whose contents are needed for reconciliation; the other two are explicitly preserved diagnostic scripts. Hashes alone cannot establish their behavior or reconstruct their changes.

## Evidence and limits

- Canonical readiness file SHA-256: `e2ff14d585dc46834c706b93a7cdd95199b23a2ac0734a53bba74ace34359dc5`; installed source fingerprint: `9b9472457a13a08993dcd7e87fce2115925df674a0db94c74df28344e74db6f5`.
- Base: `aa3664e420fe4fdf538cd434e4c91e73ee0875cf`; candidate: `b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b`. Parent verified candidate, staging merge, and published main share tree `fde9305a181f24815d8099ea3671f3db0a93ee79`; this is not proof of installed or worker-loaded bytes.
- Inspected all 12,966 locally available Git objects, including unreachable cached objects, using object type/size followed by SHA-256 of every size-compatible blob. Reachable history contains 524 commits and 12,713 objects. All 11 matches below are reachable.
- Inspected 30,579 regular cached files under `.runtime`, pruning directories named `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and `.tox`; hashed all 62 size-compatible files. Inspected the locally cached broker release archive and other small archive metadata/members. No exact copy of the 10 unresolved paths was found. This scope is local, not all remote history or all historical releases.
- A blob present at an ancestor of main proves known main-history source, not that the entire historical tree was deployed together. Public/deployment caches provide additional evidence where stated.

## Exact Git matches

| Installed path | Installed SHA-256 | Matching Git blob OID and witness |
| --- | --- | --- |
| `app/ALPACA_PAPER_TRADING.md` | `ad1a53860e54134962e88c777fbfad12674bdf84a74a8091540cd1670fc0ade6` | `cde6f3b8119940eb427180f361eec76097dfce5d`; same path at main ancestor `0a82e65fb4c5f59bc6557e3a9e9b094e1c28ca28` |
| `app/BROKER_OAUTH.md` | `e9417c276332915c89a7c7f9e26bd073ac88ed49137c3d905bdcf623451e9d64` | `548e8ce93a05718fece455d422ada10a23da42f6`; same path at main ancestor `c11348ce83bdf30282cf24b1942e8e8061588fac` |
| `app/BROKER_OAUTH_DEPLOYMENT.md` | `b4a198715d72d8da2fa207cd0f5626200fea2dd57cd1c796e9f0e1deca3e9ccb` | `fab6b0cb552e8d2bf5f837aa721ba89c10df2dcb`; same path at `c11348ce83bdf30282cf24b1942e8e8061588fac` |
| `app/README.md` | `15daf953c998b18744c8793aa3545c97ce55a03f81d3f5caa0ea78a7f4c65877` | `b1ea1caa68d9ec4eacc320f26fc5ad5f64086ce1`; same path at `c11348ce83bdf30282cf24b1942e8e8061588fac` |
| `app/broker_oauth.py` | `a92b71ddf2e97487d5f6423fdc12e2f872cf11569ac007d4b456e8824550ef26` | `7c5c6af7f3b819f255da30bcc9836fbc47905d0b`; same path at main ancestor `473d6249f5dfd0f6e464d9ffaaf9467513a6fd99`; exact cached broker-release archive member |
| `app/static/broker-connections.js` | `9cefce2fcf2ac6c2ed5a9dbfeff915da2d9a09cec314317af9c9ecd4a63b30ce` | `952dfeba9aa1fca481e269147544ed13360e9af8`; same path at `473d6249f5dfd0f6e464d9ffaaf9467513a6fd99`; exact broker-release archive and deployed-public-source cache |
| `app/static/app.meridian.js` | `b457ecf5d4720adaf27635712f4e2c7745e72b8ca3c02c4efa8c457423046b77` | `ddac16001d40706d7d5b7fd12ac7f9a97e930c7e`; same path at `473d6249f5dfd0f6e464d9ffaaf9467513a6fd99`; exact broker-release archive and deployed-public-source cache |
| `app/static/index.html` | `e0be2fb9c644388399da2a2e50ab06564ec4b8dd45c8106b01aa456b0bf5585f` | `009b9e8f7448b6ee657f3723aba00f07f5cb94b6`; same path at main ancestor `3c70435aca66e8d244e15114d22b7d1f571c3ace`; later operations manifest explicitly preserves it |
| `app/static/app.meridian.css` | `1e7978ec34364065b51e61dcdf8a5099085dc8ab5f8da72009166d4596059c0e` | `69feaee24c42f17c4c6877af403f7d4cc1a43103`; same path at main ancestor `2223751625dbdf3f07710ac27b58180fcadac23f`; exact broker-release archive member |
| `app/static/app.css` | `24392a8f61da64a9db002e471f4dbf516a09d83f701007f8db0cb5b616b5a2d7` | `9d9bd3df7ccfe2276c2b3eb17a1c957106141655`; operations commit `5b801468a300ed226a4e756de704f262bfc4d7d6`, path `results/header_alignment_operations_2026-10-22/candidate.css`; exact recorded header-restoration candidate, not base main's stylesheet |
| `data_pipeline/research_expiry_resolution.py` | `8a9bc3cfa6d4f9792bc389faf1f08ee2506d785624265fa7f85ae522ebd3a418` | `35d15d5e7616fa793ef341ec26f198c106d128e6`; exists in base main at `research/expiry_resolution.py`, a different path; Oct19 preservation receipt records the installed diagnostic path |

## Unresolved exact source matches

| Installed path | Bytes | Installed SHA-256 | Additional provenance |
| --- | ---: | --- | --- |
| `app/agent.py` | 173625 | `c78ee13f989b038e4bafc24da684a851bf2121dc8ac70827f9c442ef9902c4da` | No exact local source or older exact hash witness found |
| `app/billing.py` | 13576 | `0fd9b234d03df7db3c83ac0c45f487063f8eaa37f677fcfa37971708d3d3baef` | No exact local source or older exact hash witness found |
| `app/devlog.py` | 101322 | `913520e1fd7686a689b4738ed8a7d8eb14540b9497131cccdea80075cc80fab7` | No exact local source or older exact hash witness found |
| `app/llm.py` | 22318 | `1ce41cbc588c116d26adc33c041b4576ed793fe188146229cb1367cfd7129444` | No exact local source or older exact hash witness found |
| `app/repository.py` | 102323 | `2cb1037da11b513f6389cbfd5eb139e9861b718e37de09b0ef64fcdc962fc5c7` | No exact local source or older exact hash witness found |
| `app/schema.py` | 39642 | `6738460234b7e46ff230cb64e287354e2e3e0f46a548f8fb504ef17c476c1084` | Same hash appears in Oct21 Meridian deployment inventories and `RESTORE_PIN_REVIEW.json`; source bytes unavailable locally |
| `app/server.py` | 107139 | `8d93c845e51c7b46696725f99ab18e20c2b5ce0041f52ac56d81a0410e7cea68` | No exact local source or older exact hash witness found |
| `app/static/app.js` | 282132 | `6d290678e2b9b96887f83a7f0fd8a095d95c3df002846c656f58c6febd1742e7` | Header-operations manifest pins this exact preserved hash; no exact local source copy |
| `data_pipeline/research_expiry_resolution_sensitivity.py` | 2832 | `fe8daf9c9c7757cf6b2b7d3a8ee710b7e5d0da3ac190dff0d6f35a817085f965` | Oct19 `ON_HOST_PRESERVATION.json` and paper-deployment receipts explicitly preserve this exact hash |
| `data_pipeline/research_fee_sensitivity.py` | 2658 | `e0122dfa770991e3c6ec060a598cd14611d448409879301c0605c216fd3260e4` | Same Oct19 preservation records; source bytes unavailable locally |

## Release implication

Before replacing any of the eight unresolved application files, obtain a bounded read of those selected source files and verify the bytes against this inventory. Review their differences against base/candidate; then prepare and test a concrete reconciliation. A selected source read is sufficient for this investigation; credentials, private configuration, database records, runtime logs, or licensed data are unnecessary. Preserve both diagnostic scripts by exact hash without requiring a source export if they remain untouched.

Stage from a private clone of the installed package, preserve every unrelated installed asset/metadata and extra diagnostic path, and apply only a reviewed allowlist. A Git-main archive over the installation would overwrite known older-release assets and the header-restoration CSS, and cannot preserve unexamined application changes. Even the two perps JavaScript bundles need reconciliation with the actual installed default bundle and retained theme/bootstrap behavior.

Hash equality is a provenance fact, not acceptance of obsolete behavior: older broker/main source may intentionally differ from current main. Likewise, no-match does not prove that a file is new, unpublished, unsafe, or safe. This review does not establish active worker-loaded source, production full-schema lock safety, replay acceptance, or permission to restart workers or activate perps. Keep the earlier web-only/feature-off/retained-backup conditions in `RELEASE_REVIEW.md`; no release is accepted by this source comparison alone.
