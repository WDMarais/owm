# test_fixtures

Test assets for owm. There are **two tiers** of addon-repo fixtures, split by
cost and purpose. Keep them separate — don't let the fast unit suite pull in the
heavy runnable ones.

## The two-layer rule

For both tiers the **source lives here, versioned with the tool**; the actual git
repos owm consumes are **materialised on demand** (`copytree` → `git init` →
`git clone --bare`) into a throwaway workspace. owm's job is to operate *on*
external repos (worktree, branch, push), so the repos must be real and
independent at runtime — but their source of truth is in-tree, reviewed in PRs,
and reproducible. Never hand-mutate a materialised `_repos/*.git`; edit the
source here and re-seed.

```
source (here, in owm)  ──seed──▶  _upstream/<name>  ──clone --bare──▶  _repos/<name>.git
                                                                        (what owm worktrees)
```

## `lightweight-repos/` — Odoo-free, fast unit tests

Addon scaffolds with manifests and `depends` but **no models, no Odoo import**.
They exercise owm's own logic — addons_path resolution, manifest parsing,
`depends` ordering, `check-modules` — without booting anything.

Consumed by `tests/conftest.py` (`FIXTURE_REPOS`, the `seed="fixture"` path of
`make_upstream_repo`). Fast; in the default `pytest` run.

| repo | shape it covers |
|------|-----------------|
| `odoo_like/`      | odoo-style `odoo/addons` + `addons` layout |
| `multi_path_repo/`| one repo contributing multiple addons_paths |
| `product_core/`   | a module depending on a stdlib Odoo addon (`sale`) |
| `customer_config/`| a module depending on another fixture module |
| `scripts_repo/`   | a plain-Python `run-script` fixture (no Odoo) |

## `runnable-repos/` — real Odoo, cross-repo inherit/override smoke

Two **separate** repos that boot under a real Odoo 19 and prove the multirepo
inherit machinery across a repo boundary:

```
product-core/          # repo 1
  product_base/        #   defines model product.probe + greet() -> "core"
                       #   + a form view (the inherit target)
product-ext/           # repo 2 (SEPARATE repo, on the same addons_path)
  product_ext/         #   _inherit product.probe: adds `extra`, greet() -> "ext+"+super()
                       #   + a view inherit_id override (xpath adds `extra`)
smoke_inherit.py       # run through `owm shell`; asserts the four checks below
```

`smoke_inherit.py` emits one NDJSON row per check (owm's run-script convention):

| case | proves |
|------|--------|
| `model_registered`   | product_base loaded from the product-core repo |
| `cross_repo_field`   | `extra` merged in from product-ext's `_inherit` |
| `cross_repo_override`| `greet() == "ext+core"` — override + `super()` across repos |
| `view_inherit`       | ext view extends base view via `inherit_id` |

### Running it

Materialise a workspace with the runnable repos via the seed script, pointing at
a real bare Odoo 19 checkout:

```
python scripts/seed_ws.py ~/tmp/owm-smoke-ws \
    --odoo-repo ../dev-instances/_repos/odoo.git --with-addons
```

then follow the printed commands (`owm create … product-core=… product-ext=…`,
`owm start`, `owm install feat-test product_ext`, `owm shell … --script
smoke_inherit.py --json`). Every case should report `OK`.

This needs a real Odoo + postgres, so it is **not** part of the default `pytest`
run — it's a manual/integration smoke.
