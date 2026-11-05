# Development

This section is for people who change PowderLine or add an engine to it: how
the package is built, how to set up and test a change, and the rules every
change follows.

- [Architecture](architecture.md): the core, the gateways, and what happens
  during a run.
- [Contributing](contributing.md): set up, run the tests, build the docs,
  write documentation.
- [Add an engine or a capability](adding-an-engine.md): the gateway contract,
  step by step.
- [Policies](policies.md): versioning, deliberate changes, the frozen GSAS-II
  code, engine pins and review.
- [Internals API](internals-api.md): the modules behind the public API.
- [Migrating from 0.1](migrating-from-0.1.md): for recipes and code written
  for PowderLine 0.1.x.

```{toctree}
:maxdepth: 1
:hidden:

architecture
contributing
adding-an-engine
policies
internals-api
migrating-from-0.1
```
