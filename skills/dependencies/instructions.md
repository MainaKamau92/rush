# Dependencies and build configuration

Review changed dependency manifests, build images and CI configuration for
concrete supply-chain, compatibility and build risks that the change introduces.

Report, with the changed line as the anchor:

- packages fetched from outside the official registry, over plain HTTP, from an
  extra or untrusted index, or from an unpinned Git branch or URL;
- new install, postinstall or prepare scripts, and removed integrity hashes;
- a version forced outside the range its dependents declare (for example an
  override to a new major version), when nothing in the change shows it was
  checked or says when it can be removed;
- a dropped runtime or engine version that the repository still uses, shown by
  its configuration;
- CI changes that widen token permissions, expose secrets, or run untrusted pull
  request code with privileges;
- base images moved to a floating tag such as `latest`.

- When a lockfile is summarized in the context, use it to see added, removed or
  changed packages, their sources and install scripts. Cite the summary as
  evidence and anchor on the changed manifest line that caused it.
- Do not report routine patch or minor updates within declared ranges.
- Do not claim a package has a known vulnerability; you cannot check advisories.
- Do not judge whether the change matches its ticket; another skill does that.
- Request a related snippet only to confirm a runtime version or an existing
  usage the risk depends on.
- Never claim that code, installs or tests were run.
